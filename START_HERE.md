# SKYFRAME OBSERVATORY — one-command development launcher

This patch only adds two files at the **project root** (`start.sh` and this guide).
It does not modify `frontend/`, `backend/`, `.git/`, or any source code.

## Install from a ZIP (in the `SpaceX Project` directory)

```bash
unzip -o "$HOME/Downloads/SpaceX-One-Command-Launcher.zip" -d . && bash start.sh
```

## Every time after that

Open a terminal at the `SpaceX Project` root and run:

```bash
bash start.sh
```

Open **http://127.0.0.1:5173** in your browser.

- Frontend: React/Vite dev server with hot reload (port 5173).
- Backend: FastAPI with auto reload (port 8000).
- Backend API docs: http://127.0.0.1:8000/docs
- Vite proxies `/api` to the backend; you do not need to change the frontend API URL.
- **Ctrl+C** stops both processes.

### Automatic first-run setup

- Requires Node.js and npm to be installed already.
- Installs `uv` automatically from Astral's official installer *only if not found*.
  That installer downloads software from `https://astral.sh/uv/install.sh`.
- Runs `uv sync --locked` to create/update `backend/.venv` and install the project's Python 3.12 dependencies.
  uv may download Python 3.12 on the first run.
- Runs `npm ci` on the first run or when `frontend/package-lock.json` changes. Later starts skip it.
- Requires an internet connection the first time dependencies are installed. Real SPHEREx searches also require network access.

### If a server cannot start

- `Address already in use` on port 8000 or 5173 means another local server is already running. Stop the older server (Ctrl+C in its terminal), then rerun `bash start.sh`.
- `command not found: node` or `npm`: install Node.js 22+.
- If uv installation fails, use https://docs.astral.sh/uv/getting-started/installation/ and rerun the launcher.
- Pending API features such as spectra may still return HTTP 501; a launcher does not implement unfinished science endpoints.

### Commit the helper to GitHub (optional)

```bash
git add start.sh START_HERE.md
git commit -m "Add one-command developer launcher"
git push
```
