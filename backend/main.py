import gitingest
import os
import math
import re
from dotenv import load_dotenv
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import openai
import subprocess
from datetime import datetime
import tiktoken

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


@app.route('/generate-docs', methods=['POST'])
def generate_docs():
    # Assuming gitingest.ingest is the correct function to call
    data = request.get_json()
    repo_url = data.get('repoUrl')
    subprocess.Popen(["gitingest", repo_url, "-o", "../repo.txt"]).wait()

    # if not repo_url:
    #     return jsonify({'error': 'Repository URL is required'}), 400

    # match = re.match(r'github\.com\/([^\/]+)\/([^\/]+)', repo_url)
    # if not match:
    #     return jsonify({'error': 'Invalid GitHub URL'}), 400
    
    try:
        with open("../repo.txt", "r", encoding="utf8") as f:
            content = f.read()
        sections = content.split("================================================\n")

        # Remove any leading/trailing whitespace and empty sections
        sections = [section.strip() for section in sections if section.strip()]

        # The first section is the directory structure
        directory_structure = sections[0] if sections else ""

        # Combine every two sections starting from section 1
        combined_sections = []
        for i in range(1, len(sections), 2):
            if i + 1 < len(sections):
                combined_section = "================================================\n" + sections[i] + "\n================================================\n" + sections[i + 1]
            else:
                combined_section = "================================================\n" + sections[i]
            combined_sections.append(combined_section)

        source_code_chunks = combined_sections


        # Step 2: Generate Sphinx RST for each chunk with retry logic
        rst_parts = []
        for i, chunk in enumerate(source_code_chunks):
            print(f"Processing chunk {i + 1}/{len(source_code_chunks)}, tokens: {count_tokens(chunk)}")
            prompt = f"Generate Sphinx-compatible RST for this source code chunk (part {i + 1}/{len(source_code_chunks)}):\n\n{chunk}"
            gpt_response = call_openai_with_retry(prompt)
            rst_parts.append(gpt_response.choices[0].message.content)
        
        
        sphinx_docs = '\n\n.. raw:: html\n\n   <hr>\n\n'.join(rst_parts)

        # Step 3: Set up Sphinx structure
        sphinx_dir = "./sphinx_docs"
        source_dir = os.path.join(sphinx_dir, 'source')
        build_dir = os.path.join(sphinx_dir, 'build')

        # Write RST file
        rst_file_name = f"docs_{int(datetime.now().timestamp())}.rst"
        rst_file_path = os.path.join(source_dir, rst_file_name)
        with open(rst_file_path, 'w') as f:
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
html_theme = 'alabaster'
html_static_path = ['_static']
"""
            with open(conf_path, 'w') as f:
               f.write(conf_content)

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
        with open(index_path, 'w') as f:
            f.write(index_content)

        # Step 4: Run sphinx-build
        # sphinx_command = f"sphinx-build -b html {source_dir} {build_dir}"
        # process = asyncio.create_subprocess_exec(
        #     *sphinx_command.split(),
        #     stdout=asyncio.subprocess.PIPE,
        #     stderr=asyncio.subprocess.PIPE
        # )
        # stdout, stderr = process.communicate()
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