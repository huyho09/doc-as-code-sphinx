const express = require('express');
const axios = require('axios');
const fs = require('fs').promises;
const { OpenAI } = require('openai');
const path = require('path');
const cors = require('cors');

const app = express();
const port = 3000;

// Middleware
app.use(cors());
app.use(express.json());
app.use('/downloads', express.static(path.join(__dirname, 'generated_docs')));

// Initialize OpenAI
const openai = new OpenAI({
  apiKey: 'YOUR_OPENAI_API_KEY', // Replace with your OpenAI API key
});

// Endpoint to generate documentation
app.post('/generate-docs', async (req, res) => {
  const { repoUrl } = req.body;

  if (!repoUrl) {
    return res.status(400).json({ error: 'Repository URL is required' });
  }

  try {
    // Step 1: Fetch source code from Gitingest API (hypothetical)
    const gitingestResponse = await axios.get(`https://gitingest-api.example.com/repo?url=${repoUrl}`, {
      headers: { 'Authorization': 'Bearer YOUR_GITINGEST_TOKEN' } // Replace with actual token
    });
    const sourceCode = gitingestResponse.data.code || 'No code retrieved';

    // Step 2: Save source code to file
    const sourceFilePath = path.join(__dirname, 'generated_docs', 'source_code.txt');
    await fs.writeFile(sourceFilePath, sourceCode);

    // Step 3: Generate Sphinx docs with GPT-4o
    const prompt = `Generate Sphinx-compatible RST documentation for this source code:\n\n${sourceCode}`;
    const gptResponse = await openai.chat.completions.create({
      model: 'gpt-4o',
      messages: [{ role: 'user', content: prompt }],
      max_tokens: 1500,
    });
    const sphinxDocs = gptResponse.choices[0].message.content;

    // Step 4: Save generated RST file
    const docFileName = `docs_${Date.now()}.rst`;
    const docFilePath = path.join(__dirname, 'generated_docs', docFileName);
    await fs.writeFile(docFilePath, sphinxDocs);

    // Step 5: Send download link
    const downloadLink = `http://localhost:${port}/downloads/${docFileName}`;
    res.json({ downloadLink });
  } catch (error) {
    console.error('Error:', error.message);
    res.status(500).json({ error: 'Failed to generate documentation' });
  }
});

// Start server
app.listen(port, () => {
  console.log(`Backend running at http://localhost:${port}`);
});