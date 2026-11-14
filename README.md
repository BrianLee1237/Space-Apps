# SPHEREx Explorer

The existing React frontend is connected to the SPHEREx FastAPI backend through its
`/api` contract. FastAPI also serves the compiled frontend, so the application can
run from one local URL.

## Start the application

Install Node.js and [uv](https://docs.astral.sh/uv/getting-started/installation/),
then run these commands from the repository root.

```powershell
cd frontend
npm ci
npm run build
cd ../backend
uv sync --locked
uv run uvicorn spherex_api.app:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000> for the application and
<http://127.0.0.1:8000/docs> for the API documentation. Enter coordinates in Controls,
or select one of the five targets in Guide. Searches and FITS downloads use public
IRSA data and require no API key.

For frontend development, keep FastAPI on port 8000 and run `npm run dev` from
`frontend` in another terminal. Its existing Vite proxy forwards `/api` requests to
FastAPI. For separate frontend hosting, set `VITE_API_BASE_URL` to the backend's
absolute `/api` URL when building and set `SPHEREX_CORS_ORIGINS` on the backend to
the frontend's origin.

## Connected behavior

- Coordinate search, all five guided targets, and detector selection retrieve DR1
  and QR3 observations.
- Auto selects detector 6. Detector selection supports 1 through 6. The existing
  field-of-view options through 60 arcminutes are supported.
- The timeline uses actual observation times and loads real FITS-derived PNGs on
  demand. Frames use a common celestial grid and the first frame's brightness limits.
- Release, detector, exposure, and inspected quality metadata populate the existing
  components. Flags are included when the actual FITS metadata are cached.
- The local discovery notebook retains the frontend's existing browser storage.

Difference imaging is implemented: `/api/difference` and `/v1`-backed
`/api/difference.png` resample two observations onto one shared ICRS grid and
render a zero-centered, red/blue diverging quick-look PNG (to minus from). It is
not flux-calibrated and applies no PSF matching or background fitting; the
response's `warnings` state this. Channel-binned sequences, candidate detection,
spectral extraction, and Gaia overlays remain pending scientific implementation.
Their routes return HTTP 501, which the existing frontend displays as
unavailable. Wavelength can vary between exposures within one detector. Use the
wavelength metadata from the `/v1` API when assessing motion or variability.

Search snapshots and FITS files are stored under `backend/data` and are ignored by
Git. The Python environment and generated frontend build are also ignored. The
frontend source, styling, and assets are retained from the supplied version.

## Validation

```powershell
cd frontend
npm run build
cd ../backend
uv run pytest -q
uv run python scripts/validate_live.py --frames-per-target 2
```

The backend tests include the frontend request/response contract, image URLs,
guided targets, shared display limits, and scientific image-processing regressions.
The opt-in live check writes results under `backend/data/reports`.

Detailed archive access and processing information is available in
[the backend README](backend/README.md) and [the build plan](backend/BUILD_PLAN.md).
