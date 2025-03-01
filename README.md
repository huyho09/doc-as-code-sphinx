# DocGen: GitHub Repository Documentation Generator

## Description

DocGen is a web application that generates Sphinx-compatible HTML documentation from GitHub repository source code. It clones a specified repository using `nodegit`, processes its files in parallel with worker threads to create a `source_code.txt` file, chunks the content for GPT-4o analysis, and converts the resulting RST into HTML using `sphinx-build`. The frontend, built with Vue.js, provides a simple interface to input a GitHub repo URL and download the generated documentation.

### Key Features
- **Repository Cloning**: Uses `nodegit` to clone GitHub repos locally, avoiding API rate limits.
- **Multi-threading**: Leverages `worker_threads` to parallelize file reading and writing, speeding up `source_code.txt` generation.
- **AI-Powered Docs**: Employs GPT-4o to generate Sphinx-compatible RST from source code.
- **Vue.js Frontend**: Offers a user-friendly interface to trigger documentation generation and download results.

## Project Structure

```
doc-gen-app/
├── backend/                    # Node.js backend
│   ├── generated_docs/         # Stores source_code.txt and generated HTML
│   │   ├── source_code.txt     # Full repo source code
│   │   └── docs_<timestamp>.html # Generated HTML doc
│   ├── sphinx_docs/            # Sphinx project directory
│   │   ├── build/              # HTML output from sphinx-build
│   │   │   ├── index.html      # Final HTML doc
│   │   │   ├── _static/        # Sphinx static files
│   │   │   └── ...             # Other Sphinx files
│   │   └── source/             # Sphinx source files
│   │       ├── conf.py         # Sphinx config
│   │       ├── index.rst       # Sphinx index
│   │       └── docs_<timestamp>.rst # Generated RST
│   ├── node_modules/           # Backend dependencies
│   ├── package.json            # Backend dependencies and scripts
│   ├── package-lock.json       # Dependency lock file
│   └── server.js               # Backend server logic
├── frontend/                   # Vue.js frontend
│   ├── node_modules/           # Frontend dependencies
│   ├── public/                 # Static assets
│   │   ├── favicon.ico         # Default favicon
│   │   └── index.html          # Vue entry HTML
│   ├── src/                    # Vue source files
│   │   ├── assets/             # Static assets (e.g., logo.png)
│   │   ├── components/         # Vue components
│   │   │   └── RepoForm.vue    # Form for repo URL input
│   │   ├── App.vue             # Main Vue component
│   │   └── main.js             # Vue entry point
│   ├── package.json            # Frontend dependencies and scripts
│   └── package-lock.json       # Dependency lock file
└── README.md                   # Project documentation
```

## Installation and Setup

### Prerequisites
- **Node.js**: v18.x or later (includes npm) - [Download](https://nodejs.org/)
- **Git**: Required for `nodegit` - [Download](https://git-scm.com/)
- **Python**: 3.x for Sphinx - [Download](https://www.python.org/)
- **GitHub Token**: Generate a Personal Access Token with `repo` scope at [GitHub Settings](https://github.com/settings/tokens)

### Backend Setup
1. **Navigate to Backend Directory**:
   ```bash
   cd backend
   ```
2. **Install Dependencies**:
   ```bash
   npm install
   ```
   - Installs `cors`, `dotenv`, `express`, `nodegit`, `openai`.
   - Note: `nodegit` requires build tools (e.g., `node-gyp`, Python, Git). If installation fails, see [nodegit troubleshooting](https://github.com/nodegit/nodegit#installation).

3. **Configure Environment**:
   - Create a `.env` file in `backend/`:
     ```
     OPENAI_API_KEY=your_openai_api_key
     GITHUB_TOKEN=your_github_token
     ```
   - Replace `your_openai_api_key` with your OpenAI API key ([OpenAI Platform](https://platform.openai.com/)) and `your_github_token` with your GitHub token.

4. **Install Sphinx**:
   ```bash
   pip install sphinx
   ```
   - Optionally, install a theme like `sphinx-rtd-theme`:
     ```bash
     pip install sphinx-rtd-theme
     ```

5. **Start Backend**:
   ```bash
   npm start
   ```
   - Runs on `http://localhost:3000`.

### Frontend Setup
1. **Navigate to Frontend Directory**:
   ```bash
   cd frontend
   ```
2. **Install Dependencies**:
   ```bash
   npm install
   ```
   - Installs `axios`, `vue`, `@vue/cli`.

3. **Start Frontend**:
   ```bash
   npm run serve
   ```
   - Runs on `http://localhost:8080` (or another port if occupied).

## Usage
1. **Open Frontend**: Visit `http://localhost:8080` in your browser.
2. **Enter GitHub URL**: Input a repo URL (e.g., `https://github.com/vuejs/vue`).
3. **Submit**: Click "Submit" to trigger documentation generation.
4. **Download**: Once complete, download the generated HTML file from the provided link.
5. **Verify**: Check `backend/generated_docs/source_code.txt` for the full source code.

## Notes
- **Performance**: Multi-threading speeds up `source_code.txt` creation for repos with many directories. Flat repos (many files at root) may see less benefit without further file-level splitting.
- **Disk Space**: Cloning requires temporary space (e.g., 100MB for a medium repo). Ensure sufficient disk availability.
- **Token Accuracy**: Uses a rough `1 token ≈ 4 chars` estimate, which may overestimate tokens, leading to more chunks than necessary.
- **Memory**: Streaming keeps usage low, but reading `source_code.txt` back into memory could strain large repos.

## To-Do
- **Error Handling**: Add retry logic for `nodegit` cloning failures (e.g., network issues).
- **File Filtering**: Exclude irrelevant directories (e.g., `node_modules/`) to reduce noise in `source_code.txt`.
- **Progress Feedback**: Send real-time progress updates to the frontend during cloning and processing.
- **Worker Pool**: Limit concurrent workers to avoid overwhelming system resources.

## Future Improvements
- **Optimize Flat Repos**: Split root-level files across workers for repos with many files in a single directory.
- **Custom Extensions**: Allow users to specify file extensions via the frontend.
- **Incremental Updates**: Support updating docs for only changed files in a repo, avoiding full re-clones.
- **Better Tokenization**: Integrate a lighter tokenization library (e.g., a JS-based alternative) for more accurate chunking without WebAssembly issues.
- **Caching**: Cache cloned repos locally to skip re-cloning for repeated requests.

## Troubleshooting
- **Nodegit Installation**: If `npm install nodegit` fails, ensure Git, Python, and build tools (e.g., `gcc`) are installed. See [nodegit docs](https://github.com/nodegit/nodegit#installation).
- **Permission Denied**: Ensure the backend has write access to `generated_docs/` and `sphinx_docs/`.
- **Rate Limits**: If GPT-4o hits rate limits, adjust `retries` or `delay` in `callOpenAIWithRetry`.

---

This `README.md` provides a comprehensive guide to your project, covering its purpose, structure, setup, usage, and potential enhancements. Let me know if you’d like to tweak any section further!