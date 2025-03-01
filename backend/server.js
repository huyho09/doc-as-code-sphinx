require('dotenv').config();
const express = require('express');
const axios = require('axios');
const fs = require('fs').promises;
const { OpenAI } = require('openai');
const path = require('path');
const cors = require('cors');
const { exec } = require('child_process');
const { Tiktoken } = require('@dqbd/tiktoken');

const app = express();
const port = 3000;

app.use(cors());
app.use(express.json());
app.use('/downloads', express.static(path.join(__dirname, 'generated_docs')));

const openai = new OpenAI({ apiKey: process.env.OPENAI_API_KEY });

// Initialize Tiktoken
let tiktoken;
try {
  tiktoken = new Tiktoken({ encoding: 'cl100k_base' });
} catch (error) {
  console.error('Failed to initialize Tiktoken:', error.message);
}

// Function to count tokens with fallback
function countTokens(text) {
  try {
    if (tiktoken) {
      return tiktoken.encode(text).length;
    }
  } catch (error) {
    console.error('Tiktoken error:', error.message);
  }
  // Fallback: Rough estimate (1 token ≈ 4 chars)
  return Math.ceil(text.length / 4);
}

// Function to recursively fetch all file contents and chunk during fetch
async function fetchAllRepoContents(owner, repo, path = '', token, extensions = ['.js', '.py', '.ts', '.md']) {
  const url = `https://api.github.com/repos/${owner}/${repo}/contents/${path}`;
  const response = await axios.get(url, { headers: { 'Authorization': `Bearer ${token}` } });
  
  const chunks = [];
  let currentChunk = '';

  for (const item of response.data) {
    if (item.type === 'file' && item.download_url && extensions.some(ext => item.path.endsWith(ext))) {
      const fileContent = await axios.get(item.download_url).then(res => res.data);
      if (fileContent.length > 500000) {
        console.warn(`Skipping large file: ${item.path} (${fileContent.length} chars)`);
        continue;
      }
      const fileText = `\n=== File: ${item.path} ===\n${fileContent}`;
      if (countTokens(currentChunk + fileText) > 25000) {
        chunks.push(currentChunk);
        currentChunk = fileText;
      } else {
        currentChunk += fileText;
      }
    } else if (item.type === 'dir') {
      const dirChunks = await fetchAllRepoContents(owner, repo, item.path, token, extensions);
      for (const dirChunk of dirChunks) {
        if (countTokens(currentChunk + dirChunk) > 25000) {
          chunks.push(currentChunk);
          currentChunk = dirChunk;
        } else {
          currentChunk += dirChunk;
        }
      }
    }
  }
  if (currentChunk) chunks.push(currentChunk);
  return chunks; // Return array of chunks instead of joined string
}

// Function to call OpenAI with retry and exponential backoff
async function callOpenAIWithRetry(prompt, retries = 3, delay = 1000) {
  for (let attempt = 0; attempt < retries; attempt++) {
    try {
      const response = await openai.chat.completions.create({
        model: 'gpt-4o',
        messages: [{ role: 'user', content: prompt }],
        max_tokens: 1500,
      });
      return response;
    } catch (error) {
      if (error.response && error.response.status === 429) {
        const waitTime = delay * Math.pow(2, attempt);
        console.log(`Rate limit hit, retrying in ${waitTime}ms... (Attempt ${attempt + 1}/${retries})`);
        await new Promise(resolve => setTimeout(resolve, waitTime));
      } else {
        throw error;
      }
    }
  }
  throw new Error('Max retries reached for OpenAI API call');
}

app.post('/generate-docs', async (req, res) => {
  const { repoUrl } = req.body;

  if (!repoUrl) {
    return res.status(400).json({ error: 'Repository URL is required' });
  }

  const match = repoUrl.match(/github\.com\/([^\/]+)\/([^\/]+)/);
  if (!match) {
    return res.status(400).json({ error: 'Invalid GitHub URL' });
  }
  const [_, repoOwner, repoName] = match;

  try {
    // Step 1: Fetch filtered source code recursively as chunks
    const sourceCodeChunks = await fetchAllRepoContents(repoOwner, repoName, '', process.env.GITHUB_TOKEN);
    if (!sourceCodeChunks || sourceCodeChunks.length === 0) {
      return res.status(400).json({ error: 'No relevant source code found (e.g., .js, .py, .ts, .md files)' });
    }
    console.log(`Generated ${sourceCodeChunks.length} chunks`);
    
    // Save full source code for reference
    const sourceCode = sourceCodeChunks.join('\n');
    console.log(`Source code size: ${sourceCode.length} characters`);
    const sourceFilePath = path.join(__dirname, 'generated_docs', 'source_code.txt');
    await fs.writeFile(sourceFilePath, sourceCode);

    // Step 2: Generate Sphinx RST for each chunk with retry logic
    const rstParts = [];
    for (let i = 0; i < sourceCodeChunks.length; i++) {
      const chunk = sourceCodeChunks[i];
      console.log(`Processing chunk ${i + 1}/${sourceCodeChunks.length}, tokens: ${countTokens(chunk)}`);
      const prompt = `Generate Sphinx-compatible RST for this source code chunk (part ${i + 1}/${sourceCodeChunks.length}):\n\n${chunk}`;
      const gptResponse = await callOpenAIWithRetry(prompt);
      rstParts.push(gptResponse.choices[0].message.content);
    }
    const sphinxDocs = rstParts.join('\n\n.. raw:: html\n\n   <hr>\n\n');

    // Step 3: Set up Sphinx structure
    const sphinxDir = path.join(__dirname, 'sphinx_docs');
    const sourceDir = path.join(sphinxDir, 'source');
    const buildDir = path.join(sphinxDir, 'build');
    await fs.mkdir(sphinxDir, { recursive: true });
    await fs.mkdir(sourceDir, { recursive: true });
    await fs.mkdir(buildDir, { recursive: true });

    // Write RST file
    const rstFileName = `docs_${Date.now()}.rst`;
    const rstFilePath = path.join(sourceDir, rstFileName);
    await fs.writeFile(rstFilePath, sphinxDocs);

    // Write minimal conf.py if not exists
    const confPath = path.join(sourceDir, 'conf.py');
    if (!await fs.stat(confPath).catch(() => false)) {
      const confContent = `
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
`;
      await fs.writeFile(confPath, confContent);
    }

    // Write index.rst
    const indexPath = path.join(sourceDir, 'index.rst');
    const indexContent = `
Welcome to DocGen's documentation!
=================================

.. toctree::
   :maxdepth: 2
   :caption: Contents:

   ${rstFileName.replace('.rst', '')}
`;
    await fs.writeFile(indexPath, indexContent);

    // Step 4: Run sphinx-build
    const sphinxCommand = `sphinx-build -b html ${sourceDir} ${buildDir}`;
    await new Promise((resolve, reject) => {
      exec(sphinxCommand, (error, stdout, stderr) => {
        if (error) {
          console.error('Sphinx Error:', stderr);
          return reject(error);
        }
        console.log('Sphinx Output:', stdout);
        resolve();
      });
    });

    // Step 5: Provide HTML download link
    const htmlFilePath = path.join(buildDir, 'index.html');
    const htmlFileName = `docs_${Date.now()}.html`;
    const downloadPath = path.join(__dirname, 'generated_docs', htmlFileName);
    await fs.copyFile(htmlFilePath, downloadPath);

    const downloadLink = `http://localhost:${port}/downloads/${htmlFileName}`;
    res.json({ downloadLink });
  } catch (error) {
    console.error('Error:', error.message);
    res.status(500).json({ error: 'Failed to generate documentation' });
  }
});

app.listen(port, () => {
  console.log(`Backend running at http://localhost:${port}`);
});