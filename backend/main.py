from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from flask_cors import CORS
from pydantic import BaseModel
import requests
import openai
import os
import subprocess
from dotenv import load_dotenv

load_dotenv()
app = FastAPI()
# Enable CORS (Allow all origins, methods, and headers)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # ✅ Allow Vue app
    allow_credentials=True,
    allow_methods=["*"],  # ✅ Allow all HTTP methods
    allow_headers=["*"],  # ✅ Allow all headers
)

@app.get("/")
def read_root():
    return {"message": "CORS is correctly configured in FastAPI!"}


class RepoRequest(BaseModel):
    repoUrl: str

GITINGEST_API = "https://api.gitingest.com/retrieve"
GPT_MODEL = "gpt-4o"

@app.post("/generate-docs")
def generate_docs(request: RepoRequest):
    repo_url = request.repoUrl

    # 1. Fetch source code from GitHub using Gitingest API
    response = requests.post(GITINGEST_API, json={"repo_url": repo_url})
    if response.status_code != 200:
        raise HTTPException(status_code=400, detail="Failed to retrieve source code")
    
    source_code = response.json().get("source_code")
    if not source_code:
        raise HTTPException(status_code=400, detail="No source code found")

    # 2. Save source code to a text file
    file_path = "repo_code.txt"
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(source_code)

    # 3. Send to GPT-4o for analysis
    openai.api_key = os.getenv("OPENAI_API_KEY")
    completion = openai.chat.completions.create(
        model=GPT_MODEL,
        messages=[{"role": "system", "content": "Analyze this code and generate Sphinx documentation."},
                  {"role": "user", "content": source_code}]
    )

    doc_text = completion["choices"][0]["message"]["content"]

    # 4. Save documentation as RST file for Sphinx
    docs_path = "docs"
    os.makedirs(docs_path, exist_ok=True)
    rst_file = os.path.join(docs_path, "index.rst")

    with open(rst_file, "w", encoding="utf-8") as f:
        f.write(doc_text)

    # 5. Generate HTML documentation with Sphinx
    subprocess.run(["sphinx-build", docs_path, "docs_build"])

    # 6. Provide a download link
    return {"downloadUrl": "http://localhost:5000/docs_build/index.html"}
