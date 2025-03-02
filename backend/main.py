import os
import re
import time
import requests
import shutil
from flask import Flask, request, jsonify, send_from_directory
from openai import OpenAI
from tiktoken import get_encoding
from pathlib import Path
import subprocess

# Load environment variables
from dotenv import load_dotenv
load_dotenv()


# Set proxy environment variables
os.environ['http_proxy'] = 'http://127.0.0.1:3128'
os.environ['https_proxy'] = 'http://127.0.0.1:3128'

# Initialize Flask
app = Flask(__name__)

# OpenAI API Key
openai = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Tokenizer setup
try:
    tiktoken = get_encoding("cl100k_base")
except Exception as e:
    print(f"Failed to initialize Tiktoken: {e}")
    tiktoken = None


# Function to count tokens
def count_tokens(text):
    if tiktoken:
        try:
            return len(tiktoken.encode(text))
        except Exception as e:
            print(f"Tiktoken error: {e}")
    return len(text) // 4  # Rough estimate


# Function to fetch repo contents recursively
def fetch_repo_contents(owner, repo, path="", token=None, extensions=(".js", ".py", ".ts", ".md")):
    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    response = requests.get(url, headers=headers, proxies=PROXIES)
    response.raise_for_status()

    chunks = []
    current_chunk = ""

    for item in response.json():
        if item["type"] == "file" and item["download_url"]:
            if any(item["path"].endswith(ext) for ext in extensions):
                file_content = requests.get(item["download_url"], proxies=PROXIES).text
                if len(file_content) > 500000:
                    print(f"Skipping large file: {item['path']} ({len(file_content)} chars)")
                    continue
                file_text = f"\n=== File: {item['path']} ===\n{file_content}"
                if count_tokens(current_chunk + file_text) > 25000:
                    chunks.append(current_chunk)
                    current_chunk = file_text
                else:
                    current_chunk += file_text
        elif item["type"] == "dir":
            dir_chunks = fetch_repo_contents(owner, repo, item["path"], token, extensions)
            for dir_chunk in dir_chunks:
                if count_tokens(current_chunk + dir_chunk) > 25000:
                    chunks.append(current_chunk)
                    current_chunk = dir_chunk
                else:
                    current_chunk += dir_chunk

    if current_chunk:
        chunks.append(current_chunk)
    return chunks


# Function to call OpenAI with retry
def call_openai_with_retry(prompt, retries=3, delay=1):
    for attempt in range(retries):
        try:
            response = openai.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1500,
            )
            return response
        except requests.exceptions.RequestException as e:
            print(f"Request failed: {e}")
        except Exception as e:
            print(f"Error: {e}")
        time.sleep(delay * (2 ** attempt))
    raise Exception("Max retries reached for OpenAI API call")


@app.route("/generate-docs", methods=["POST"])
def generate_docs():
    data = request.json
    repo_url = data.get("repoUrl")

    if not repo_url:
        return jsonify({"error": "Repository URL is required"}), 400

    match = re.search(r"github\.com/([^/]+)/([^/]+)", repo_url)
    if not match:
        return jsonify({"error": "Invalid GitHub URL"}), 400

    repo_owner, repo_name = match.groups()
    token = os.getenv("GITHUB_TOKEN")

    try:
        # Step 1: Fetch source code as chunks
        source_code_chunks = fetch_repo_contents(repo_owner, repo_name, "", token)
        if not source_code_chunks:
            return jsonify({"error": "No relevant source code found"}), 400

        print(f"Generated {len(source_code_chunks)} chunks")
        source_code = "\n".join(source_code_chunks)

        # Save source code
        output_dir = Path("generated_docs")
        output_dir.mkdir(exist_ok=True)
        source_file_path = output_dir / "source_code.txt"
        source_file_path.write_text(source_code)

        # Step 2: Generate Sphinx RST for each chunk
        rst_parts = []
        for i, chunk in enumerate(source_code_chunks):
            print(f"Processing chunk {i+1}/{len(source_code_chunks)}, tokens: {count_tokens(chunk)}")
            prompt = f"Generate Sphinx-compatible RST for this source code chunk (part {i+1}/{len(source_code_chunks)}):\n\n{chunk}"
            response = call_openai_with_retry(prompt)
            rst_parts.append(response.choices[0].message.content)

        sphinx_docs = "\n\n.. raw:: html\n\n   <hr>\n\n".join(rst_parts)

        # Step 3: Setup Sphinx structure
        sphinx_dir = Path("sphinx_docs")
        source_dir = sphinx_dir / "source"
        build_dir = sphinx_dir / "build"
        source_dir.mkdir(parents=True, exist_ok=True)
        build_dir.mkdir(parents=True, exist_ok=True)

        # Write RST file
        rst_filename = f"docs_{int(time.time())}.rst"
        rst_filepath = source_dir / rst_filename
        rst_filepath.write_text(sphinx_docs)

        # Write minimal conf.py
        conf_path = source_dir / "conf.py"
        if not conf_path.exists():
            conf_path.write_text("""
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
""")

        # Write index.rst
        index_path = source_dir / "index.rst"
        index_path.write_text(f"""
Welcome to DocGen's documentation!
=================================

.. toctree::
   :maxdepth: 2
   :caption: Contents:

   {rst_filename.replace('.rst', '')}
""")

        # Step 4: Run sphinx-build
        sphinx_command = f"sphinx-build -b html {source_dir} {build_dir}"
        subprocess.run(sphinx_command, shell=True, check=True)

        # Step 5: Provide HTML download link
        html_filepath = build_dir / "index.html"
        html_filename = f"docs_{int(time.time())}.html"
        download_path = output_dir / html_filename
        shutil.copy(html_filepath, download_path)

        download_link = f"http://localhost:3000/downloads/{html_filename}"
        return jsonify({"downloadLink": download_link})

    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"error": "Failed to generate documentation"}), 500


@app.route("/downloads/<path:filename>")
def download_file(filename):
    return send_from_directory("generated_docs", filename)


if __name__ == "__main__":
    app.run(port=3000, debug=True)
