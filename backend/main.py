import glob
import math
import os
import re
import shutil
import subprocess
from datetime import datetime

import openai
import tiktoken
from dotenv import load_dotenv
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

import concurrent.futures
import gitingest

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
openai.api_key = os.getenv("OPENAI_API_KEY")

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


# Asynchronous function to call OpenAI with retry and exponential backoff
def call_openai_with_retry(prompt):

    response = openai.chat.completions.create(
        model='gpt-4o',
        messages=[{'role': 'user', 'content': prompt}],
        max_tokens=15000
    )
    return response


def separate_chunk(repo_file="../repo.txt"):
    with open(repo_file, "r", encoding="utf-8") as f:
        content = f.read()

    chunks = []

    sections = content.split("================================================\n")
    sections = [section.strip() for section in sections if section.strip()]

    # First section is the directory structure
    directory_structure = sections[0] if sections else ""

    chunks.append(directory_structure)
    for i in range(1, len(sections), 2):
        if i + 1 < len(sections):
            chunk = "================================================\n" + sections[i] + "\n================================================\n" + sections[i + 1]
        else:
            chunk = "================================================\n" + sections[i]
        chunks.append(chunk)

    return chunks


def validate_repo_url(repo_url):
    try:
        # Validate accessible
        process = subprocess.Popen(['curl', '-I', repo_url], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = process.communicate()
        
        status_line = stdout.decode().splitlines()[0]
        status_code = int(status_line.split()[1])

        if status_code not in (200, 301):
            if status_code in (404, 302):
                return False
            else:
                raise RuntimeError(f"Unexpected status code: {status_code}")

        # Validate format
        git_url_regex = re.compile(
            r'^(https?|git|ssh|ftp|ftps)://' # Protocol
            r'(([\w.-]+)@)?'                 # Optional user
            r'([\w.-]+)'                     # Domain
            r'(:\d+)?'                       # Optional port
            r'(/[\w./-]+/[\w-]+)$'           # Exclude special characters
        )

        match = bool(git_url_regex.match(repo_url))
        return match

    except Exception as e:
        print(f"Error validating URL {repo_url}: {e}")
        return False

def generate_rst(source_code_chunks):    
    rst_parts = []
    total_chunks = len(source_code_chunks)

    def process_chunk(i, chunk, total_chunks):
        print(f"Processing chunk {i + 1}/{total_chunks}, tokens: {count_tokens(chunk)}")
        if count_tokens(chunk) > 15000:
            return "file too large"
        else:
            prompt = f"Generate Sphinx-compatible RST without any GPT comment for this source code chunk (part {i + 1}/{total_chunks}):\n\n{chunk}"
            gpt_response = call_openai_with_retry(prompt)

            return gpt_response.choices[0].message.content
    
    max_workers = 4

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(process_chunk, i, chunk, total_chunks): i for i, chunk in enumerate(source_code_chunks)}
        for future in concurrent.futures.as_completed(futures):
            rst_parts.append(future.result())

    return rst_parts


def remove_files_by_pattern(directory, pattern):
    full_pattern = os.path.join(directory, pattern)
    
    files_to_remove = glob.glob(full_pattern)
    
    for file_path in files_to_remove:
        try:
            os.remove(file_path)
            print(f"Removed: {file_path}")
        except Exception as e:
            print(f"Error removing {file_path}: {e}")
    

@app.route('/generate-docs', methods=['POST'])
def generate_docs():
    data = request.get_json()
    repo_url = data.get('repoUrl')
    
    
    # Clean up source and build by removing completely /build and all docs_*.rst from /source
    remove_files_by_pattern("../backend/sphinx_docs/source", "docs_*.rst")
    remove_files_by_pattern("../backend/sphinx_docs/build", "*.*")

    if not validate_repo_url:
        return jsonify({'error': 'Invalid GitHub URL'}), 400
    
    subprocess.Popen(["gitingest", f"{repo_url}", "-o", "../repo.txt"]).wait()

    if not os.path.exists("../repo.txt"):
        return jsonify({'error': 'gitingest malfunction'}), 400
    
    try:    
        source_code_chunks = separate_chunk("../repo.txt")

        # Step 2: Generate Sphinx RST for each chunk with retry logic
        rst_parts = generate_rst(source_code_chunks=source_code_chunks)
        
        
        sphinx_docs = '\n\n.. raw:: html\n\n   <hr>\n\n'.join(rst_parts)

        # Step 3: Set up Sphinx structure
        sphinx_dir = "./sphinx_docs"
        source_dir = os.path.join(sphinx_dir, 'source')
        build_dir = os.path.join(sphinx_dir, 'build')

        # Write RST file
        rst_file_name = f"docs_{int(datetime.now().timestamp())}.rst"
        rst_file_path = os.path.join(source_dir, rst_file_name)
        with open(rst_file_path, 'w', encoding="utf-8") as f:
            f.write(sphinx_docs)

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
html_theme = 'sphinx_rtd_theme'
html_static_path = ['_static']
"""
            with open(conf_path, 'w') as f:
               f.write(conf_content)

        # Write index.rst
        index_path = os.path.join(source_dir, 'index.rst')
        index_content = f"""
Welcome to DocGen's documentation!
==================================

.. toctree::
   :maxdepth: 2
   :caption: Contents:

   {rst_file_name.replace('.rst', '')}
"""
        with open(index_path, 'w', encoding="utf-8") as f:
            f.write(index_content)

        process = subprocess.call(["uv", "run", "sphinx-build", "-b", "html", source_dir, build_dir])

        # Step 5: Provide HTML download link
        html_file_name = f"docs_{int(datetime.now().timestamp())}.html"
        html_file_path = os.path.join(build_dir, 'index.html')
        download_path = os.path.join(app.config['DOWNLOAD_FOLDER'], html_file_name)
        os.rename(html_file_path, download_path)  # Move file to downloads folder

        download_link = f"http://localhost:{port}/downloads/{html_file_name}"
        return jsonify({'downloadLink': download_link})

    except Exception as e:
        print(f"Error: {str(e)}")
        return jsonify({'error': 'Failed to generate documentation'}), 500

if __name__ == '__main__':
    port = 3000
    app.run(host='127.0.0.1', port=port, debug=True)