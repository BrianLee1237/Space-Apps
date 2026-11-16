# Deploy SKYFRAME OBSERVATORY

The app includes a **single-origin production Dockerfile**: React is built at image-build time, then FastAPI serves both the React files and `/api/*` from the same host. It does not need SPHEREx credentials.

## Before deployment

From the repository root, verify locally:

```bash
cd frontend && npm ci && npm run build && cd ..
cd backend && uv sync --locked && uv run pytest -q && cd ..
```

Install Docker, then test the production image locally:

```bash
docker build -t spherex-explorer .
docker run --rm -p 8000:8000 -e SPHEREX_CACHE_BUDGET_MB=512 spherex-explorer
```

Open `http://localhost:8000` and `http://localhost:8000/health`. Test the five guided targets, image timeline, matching, tracking, comparison, PDF export, and empty/error states with real archive data.

## Deploy to a container hosting provider

1. Commit **Dockerfile**, **.dockerignore**, and the application source to your repository.
2. Create a web service using the repository's **Dockerfile** at its root (example: Render Web Service / Docker, or Railway Dockerfile deployment).
3. Set the app's public port to **8000** or allow the provider to set `PORT` automatically. Ensure the plan supports the application memory and long-running archive requests.
4. Set `SPHEREX_DATA_DIR=/data` and optionally attach a persistent writable disk mounted at `/data` to avoid repeating FITS downloads. Without a disk the cache is ephemeral. The process runs as non-root UID 10001.
5. Open the generated HTTPS URL and verify the health endpoint and a real search from a **different device**.

## Important production limitations

- The Python process downloads public FITS cutouts from NASA/IPAC IRSA. A host needs outbound HTTPS internet access; no results can be guaranteed for a specific time or coordinate.
- API requests can be expensive; this project has **no per-user authorization or rate limiting**. For an open public deployment, put network-level rate limits in front of it and monitor compute/storage use.
- Large archive searches can take minutes. The backend currently limits downloaded frame and cache sizes, but hosting providers may impose request timeouts.
- Not a NASA service or an officially validated discovery pipeline. The 102 wavelength channels are approximate spectral-WCS slices; centroid tracking, differences and pixel spectra are quick-look calculations.
- The public application is hosted on Railway. [Open SKYFRAME OBSERVATORY](https://space-apps-production.up.railway.app/?epoch=30&view=explorer)
