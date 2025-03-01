const express = require('express');
const axios = require('axios');
const fs = require('fs');
const path = require('path');
const cors = require('cors');
const { exec } = require('child_process');
require('dotenv').config();

const app = express();
app.use(express.json());
app.use(cors());

const PORT = 3000;
const GIT_INGEST_API = "https://api.gitingest.com/fetch";
const OPENAI_API_KEY = process.env.OPENAI_API_KEY;

const docsDir = path.join(__dirname, 'docs');
const htmlOutputDir = path.join(docsDir, 'build/html');

app.post('/generate-docs', async (req, res) => {
    const { repoUrl } = req.body;
    if (!repoUrl) return res.status(400).json({ success: false, message: "Repository URL is required" });

    try {
        console.log(`Fetching source code from ${repoUrl}...`);
        const gitResponse = await axios.post(GIT_INGEST_API, { url: repoUrl });
        if (!gitResponse.data || !gitResponse.data.source_code) {
            return res.status(500).json({ success: false, message: "Failed to fetch repository source code" });
        }

        const sourceCode = gitResponse.data.source_code;
        const rstFilePath = path.join(docsDir, 'index.rst');

        console.log("Generating Sphinx documentation using OpenAI...");
        const openAiResponse = await axios.post(
            "https://api.openai.com/v1/chat/completions",
            {
                model: "gpt-4o",
                messages: [
                    { role: "system", content: "You are an AI that generates Sphinx documentation from source code." },
                    { role: "user", content: `Generate a complete Sphinx documentation from the following source code:\n\n${sourceCode}` }
                ]
            },
            { headers: { "Authorization": `Bearer ${OPENAI_API_KEY}` } }
        );

        if (!openAiResponse.data || !openAiResponse.data.choices[0].message.content) {
            return res.status(500).json({ success: false, message: "Failed to generate documentation" });
        }

        const sphinxDocs = openAiResponse.data.choices[0].message.content;
        fs.writeFileSync(rstFilePath, sphinxDocs, 'utf-8');

        console.log("Sphinx documentation saved. Building HTML...");

        // Ensure docs directory has conf.py
        const confPyPath = path.join(docsDir, 'conf.py');
        if (!fs.existsSync(confPyPath)) {
            fs.writeFileSync(confPyPath, `
import os
import sys
sys.path.insert(0, os.path.abspath('.'))
project = 'Generated Docs'
extensions = []
templates_path = ['_templates']
exclude_patterns = []
html_theme = 'alabaster'
`, 'utf-8');
        }

        exec(`sphinx-build -b html ${docsDir} ${htmlOutputDir}`, (error, stdout, stderr) => {
            if (error) {
                console.error(`Sphinx build error: ${stderr}`);
                return res.status(500).json({ success: false, message: "Failed to generate HTML documentation" });
            }

            console.log("Sphinx HTML documentation built successfully.");
            res.json({ success: true, previewUrl: `http://localhost:${PORT}/docs/index.html` });
        });

    } catch (error) {
        console.error("Error:", error);
        res.status(500).json({ success: false, message: "Server error while processing" });
    }
});

app.use('/docs', express.static(htmlOutputDir));

app.listen(PORT, () => {
    console.log(`Server running on http://localhost:${PORT}`);
});
