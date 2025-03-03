import os
import asyncio
import math
import re
from dotenv import load_dotenv
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from openai import AsyncOpenAI
import aiofiles
import subprocess
from datetime import datetime
import tiktoken
from gitingest import ingest  # Import gitingest

# Load environment variables from .env
load_dotenv()

# Set proxy environment variables
os.environ['http_proxy'] = 'http://localhost:3128'
os.environ['https_proxy'] = 'http://localhost:3128'
os.environ['no_proxy'] = 'http://localhost:3128'

app = Flask(__name__)
CORS(app)  # Enable CORS
app.config['DOWNLOAD_FOLDER'] = os.path.join(os.path.dirname(__file__), 'generated_docs')

# Ensure download folder exists
os.makedirs(app.config['DOWNLOAD_FOLDER'], exist_ok=True)
app.add_url_rule('/downloads/<filename>', 'downloads', lambda filename: send_from_directory(app.config['DOWNLOAD_FOLDER'], filename))

# Initialize OpenAI client
openai = AsyncOpenAI(api_key=os.getenv('OPENAI_API_KEY'))

# Initialize Tiktoken
try:
    tiktoken_encoding = tiktoken.get_encoding('cl100k_base')
except Exception as e:
    print(f"Failed to initialize Tiktoken: {e}")
    tiktoken_encoding = None

# Function to count tokens with fallback
def count_tokens(text):
    try:
        if tiktoken_encoding:
            return len(tiktoken_encoding.encode(text))
    except Exception as e:
        print(f"Tiktoken error: {e}")
    # Fallback: Rough estimate (1 token ≈ 4 chars)
    return math.ceil(len(text) / 4)

# Asynchronous function to fetch repo contents using gitingest and chunk
async def fetch_all_repo_contents(repo_url, extensions=['.js', '.py', '.ts', '.md']):
    # Use gitingest to fetch repo content
    summary, tree, content = ingest(repo_url)
    
    # Since gitingest returns content as a string, we'll chunk it here
    chunks = []
    current_chunk = ''
    
    # Split content by lines and chunk based on token limit
    lines = content.split('\n')
    for line in lines:
        if line.strip():  # Skip empty lines
            file_text = line if not line.startswith('=== File:') else f"\n{line}"  # Preserve formatting
            if count_tokens(current_chunk + file_text) > 25000:
                chunks.append(current_chunk)
                current_chunk = file_text
            else:
                current_chunk += file_text
    
    if current_chunk:
        chunks.append(current_chunk)
    
    return chunks

# Asynchronous function to call OpenAI with retry and exponential backoff
async def call_openai_with_retry(prompt, retries=3, delay=1000):
    for attempt in range(retries):
        try:
            response = await openai.chat.completions.create(
                model='gpt-4o',
                messages=[{'role': 'user', 'content': prompt}],
                max_tokens=30000
            )
            return response
        except Exception as e:
            if hasattr(e, 'response') and e.response.status_code == 429:
                wait_time = delay * (2 ** attempt)
                print(f"Rate limit hit, retrying in {wait_time}ms... (Attempt {attempt + 1}/{retries})")
                await asyncio.sleep(wait_time / 1000)  # Convert ms to seconds
            else:
                raise e
    raise Exception('Max retries reached for OpenAI API call')

@app.route('/generate-docs', methods=['POST'])
async def generate_docs():
    data = request.get_json()
    repo_url = data.get('repoUrl')

    if not repo_url:
        return jsonify({'error': 'Repository URL is required'}), 400

    match = re.match(r'github\.com\/([^\/]+)\/([^\/]+)', repo_url)
    if not match:
        return jsonify({'error': 'Invalid GitHub URL'}), 400
    
    try:
        # Step 1: Fetch filtered source code recursively as chunks using gitingest
        source_code_chunks = await fetch_all_repo_contents(repo_url)
        if not source_code_chunks or len(source_code_chunks) == 0:
            return jsonify({'error': 'No relevant source code found (e.g., .js, .py, .ts, .md files)'}), 400
        
        print(f"Generated {len(source_code_chunks)} chunks")
        
        # Save full source code for reference
        source_code = '\n'.join(source_code_chunks)
        print(f"Source code size: {len(source_code)} characters")
        source_file_path = os.path.join(app.config['DOWNLOAD_FOLDER'], 'source_code.txt')
        async with aiofiles.open(source_file_path, 'w') as f:
            await f.write(source_code)

        # Step 2: Generate Sphinx RST for each chunk with retry logic
        rst_parts = []
        for i, chunk in enumerate(source_code_chunks):
            print(f"Processing chunk {i + 1}/{len(source_code_chunks)}, tokens: {count_tokens(chunk)}")
            prompt = f"Generate Sphinx-compatible RST for this source code chunk (part {i + 1}/{len(source_code_chunks)}):\n\n{chunk}"
            gpt_response = await call_openai_with_retry(prompt)
            rst_parts.append(gpt_response.choices[0].message.content)
        
        sphinx_docs = '\n\n.. raw:: html\n\n   <hr>\n\n'.join(rst_parts)

        # Step 3: Set up Sphinx structure
        sphinx_dir = os.path.join(os.path.dirname(__file__), 'sphinx_docs')
        source_dir = os.path.join(sphinx_dir, 'source')
        build_dir = os.path.join(sphinx_dir, 'build')
        os.makedirs(sphinx_dir, exist_ok=True)
        os.makedirs(source_dir, exist_ok=True)
        os.makedirs(build_dir, exist_ok=True)

        # Write RST file
        rst_file_name = f"docs_{int(datetime.now().timestamp())}.rst"
        rst_file_path = os.path.join(source_dir, rst_file_name)
        async with aiofiles.open(rst_file_path, 'w') as f:
            await f.write(sphinx_docs)

        # Write minimal conf.py if not exists
        conf_path = os.path.join(source_dir, 'conf.py')
        if not os.path.exists(conf_path):
            conf_content = """
import os
import sys
sys.path.insert(0, os.path.abspath('.'))
project = 'DocGen'
author = 'Auto-generated'
release = '1.0'
extensions = []
templates_path = ['_templates']
exclude_patterns = []
html_theme = 'alabaster'
html_static_path = ['_static']
"""
            async with aiofiles.open(conf_path, 'w') as f:
                await f.write(conf_content)

        # Write index.rst
        index_path = os.path.join(source_dir, 'index.rst')
        index_content = f"""
Welcome to DocGen's documentation!
=================================

.. toctree::
   :maxdepth: 2
   :caption: Contents:

   {rst_file_name.replace('.rst', '')}
"""
        async with aiofiles.open(index_path, 'w') as f:
            await f.write(index_content)

        # Step 4: Run sphinx-build
        sphinx_command = f"sphinx-build -b html {source_dir} {build_dir}"
        process = await asyncio.create_subprocess_exec(
            *sphinx_command.split(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            print(f"Sphinx Error: {stderr.decode()}")
            raise Exception('Sphinx build failed')
        print(f"Sphinx Output: {stdout.decode()}")

        # Step 5: Provide HTML download link
        html_file_name = f"docs_{int(datetime.now().timestamp())}.html"
        html_file_path = os.path.join(build_dir, 'index.html')
        download_path = os.path.join(app.config['DOWNLOAD_FOLDER'], html_file_name)
        await aiofiles.os.rename(html_file_path, download_path)  # Move file to downloads folder

        download_link = f"http://localhost:{port}/downloads/{html_file_name}"
        return jsonify({'downloadLink': download_link})

    except Exception as e:
        print(f"Error: {str(e)}")
        return jsonify({'error': 'Failed to generate documentation'}), 500

if __name__ == '__main__':
    port = 3000
    app.run(host='0.0.0.0', port=port, debug=True)