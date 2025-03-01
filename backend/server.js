require('dotenv').config();
const express = require('express');
const axios = require('axios');
const fs = require('fs').promises;
const { createWriteStream } = require('fs');
const { OpenAI } = require('openai');
const path = require('path');
const cors = require('cors');
const { exec } = require('child_process');
const { Worker, isMainThread, parentPort, workerData } = require('worker_threads');

const app = express();
const port = 3000;

app.use(cors());
app.use(express.json());
app.use('/downloads', express.static(path.join(__dirname, 'generated_docs')));

const openai = new OpenAI({ apiKey: process.env.OPENAI_API_KEY });

// Function to estimate tokens (1 token ≈ 4 chars)
function countTokens(text) {
  return Math.ceil(text.length / 4);
}

// Worker thread logic for fetching file contents
if (!isMainThread) {
  const { owner, repo, path, token, extensions } = workerData;
  
  async function fetchDirContents() {
    let contents = [];
    const perPage = 100;
    let page = 1;

    while (true) {
      const url = `https://api.github.com/repos/${owner}/${repo}/contents/${path}?per_page=${perPage}&page=${page}`;
      const response = await axios.get(url, { headers: { 'Authorization': `Bearer ${token}` } });
      const items = response.data;

      if (!items || items.length === 0) break;

      for (const item of items) {
        if (item.type === 'file' && item.download_url && extensions.some(ext => item.path.endsWith(ext))) {
          const fileContent = await axios.get(item.download_url).then(res => res.data);
          if (fileContent.length > 500000) {
            console.warn(`Worker ${workerData.path}: Skipping large file: ${item.path} (${fileContent.length} chars)`);
            continue;
          }
          contents.push(`\n=== File: ${item.path} ===\n${fileContent}`);
        }
      }

      page++;
    }

    parentPort.postMessage(contents.join('\n')); // Send content back to main thread
  }

  fetchDirContents().catch(err => parentPort.postMessage({ error: err.message }));
  process.exit(); // Exit worker after completion
}

// Main thread function to fetch and coordinate workers
async function fetchAllRepoContents(owner, repo, token, outputFile, extensions = ['.js', '.py', '.ts', '.md']) {
  const writeStream = createWriteStream(outputFile, { flags: 'w' });
  let workerCount = 0;
  let completedWorkers = 0;

  // Fetch root directory to identify subdirectories and files
  const rootUrl = `https://api.github.com/repos/${owner}/${repo}/contents?per_page=100&page=1`;
  const rootResponse = await axios.get(rootUrl, { headers: { 'Authorization': `Bearer ${token}` } });
  const rootItems = rootResponse.data;

  // Write root-level files directly
  for (const item of rootItems) {
    if (item.type === 'file' && item.download_url && extensions.some(ext => item.path.endsWith(ext))) {
      const fileContent = await axios.get(item.download_url).then(res => res.data);
      if (fileContent.length > 500000) {
        console.warn(`Main: Skipping large file: ${item.path} (${fileContent.length} chars)`);
        continue;
      }
      writeStream.write(`\n=== File: ${item.path} ===\n${fileContent}`);
    }
  }

  // Spawn workers for directories
  const directories = rootItems.filter(item => item.type === 'dir');
  workerCount = directories.length;

  if (workerCount === 0) {
    writeStream.end();
    await new Promise(resolve => writeStream.on('finish', resolve));
    return;
  }

  const workers = directories.map(dir => {
    return new Promise((resolve, reject) => {
      const worker = new Worker(__filename, {
        workerData: { owner, repo, path: dir.path, token, extensions }
      });

      worker.on('message', (data) => {
        if (typeof data === 'string') {
          writeStream.write(data); // Write worker's content to file
        } else if (data.error) {
          console.error(`Worker error for ${dir.path}: ${data.error}`);
        }
      });

      worker.on('exit', () => {
        completedWorkers++;
        if (completedWorkers === workerCount) {
          writeStream.end();
        }
        resolve();
      });

      worker.on('error', reject);
    });
  });

  await Promise.all(workers);
  await new Promise(resolve => writeStream.on('finish', resolve));
}

// Function to chunk source code based on token count
function chunkSourceCode(sourceCode, maxTokens = 10000) {
  const chunks = [];
  let currentChunk = '';
  const lines = sourceCode.split('\n');

  for (const line of lines) {
    const lineTokens = countTokens(line);
    const currentChunkTokens = countTokens(currentChunk);

    if (currentChunkTokens + lineTokens > maxTokens) {
      chunks.push(currentChunk);
      currentChunk = line;
    } else {
      currentChunk += (currentChunk ? '\n' : '') + line;
    }
  }
  if (currentChunk) chunks.push(currentChunk);
  return chunks;
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
    // Step 1: Fetch all source code and write incrementally to file with workers
    const sourceFilePath = path.join(__dirname, 'generated_docs', 'source_code.txt');
    await fetchAllRepoContents(repoOwner, repoName, process.env.GITHUB_TOKEN, sourceFilePath);

    // Step 2: Read the saved source code
    const sourceCode = await fs.readFile(sourceFilePath, 'utf8');
    if (!sourceCode) {
      return res.status(400).json({ error: 'No relevant source code found (e.g., .js, .py, .ts, .md files)' });
    }
    console.log(`Source code size: ${sourceCode.length} characters`);

    // Step 3: Chunk the source code for GPT-4o
    const sourceCodeChunks = chunkSourceCode(sourceCode);
    console.log(`Generated ${sourceCodeChunks.length} chunks`);

    // Step 4: Generate Sphinx RST for each chunk with retry logic
    const rstParts = [];
    for (let i = 0; i < sourceCodeChunks.length; i++) {
      const chunk = sourceCodeChunks[i];
      console.log(`Processing chunk ${i + 1}/${sourceCodeChunks.length}, tokens: ${countTokens(chunk)}`);
      const prompt = `Generate Sphinx-compatible RST for this source code chunk (part ${i + 1}/${sourceCodeChunks.length}):\n\n${chunk}`;
      const gptResponse = await callOpenAIWithRetry(prompt);
      rstParts.push(gptResponse.choices[0].message.content);
    }
    const sphinxDocs = rstParts.join('\n\n.. raw:: html\n\n   <hr>\n\n');

    // Step 5: Set up Sphinx structure
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

    // Step 6: Run sphinx-build
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

    // Step 7: Provide HTML download link
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