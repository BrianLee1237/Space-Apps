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
response's `warnings` state this. The two frames are reordered into true
chronological order by their own observation time regardless of which one the
caller labeled `fromId`/`toId`, with a warning if that required a swap or if
the two frames came from searches with a different field center or FOV.

The Gaia DR3 catalog overlay is implemented: `/api/overlays?observationId=...`
queries ESA's public Gaia Archive TAP+ service for sources within the frame's
field, applies a linear proper-motion approximation from each source's own
Gaia DR3 reference epoch to the observation's own epoch, and projects them
onto the same output grid the preview PNG uses. No parallax or radial-velocity
correction is applied; the response's `warnings` say so, including when a
source had no proper-motion solution at all.

Candidate detection is implemented: `/api/candidates?ra=&dec=&fov=&ids=...`
takes the earliest and latest of the given observations by actual observation
time, differences them, subtracts a local median background (two independent
exposures rarely share the same large-scale zodiacal/flat-fielding background),
and flags blobs far above the noise as candidates. A brightened blob paired
with a nearby dimmed blob is reported as a `moving-source`; an unpaired one is
a `brightness-change`. This is a best-effort statistical screen, not a
validated pipeline: it has no PSF fitting or catalog cross-match, pixels near
a bright/saturated star are excluded as likely detector overflow rather than
real flux, and the response's `warnings` say so. At most the 8 most
significant candidates are returned per request.

Channel wavelength-window selection now uses the official 102-row calibration
summary and masks pixels outside the selected window. Clicking an image returns
measured quick-look spectral samples from up to 16 exposures in the current detector
sequence. Full-band PSF-corrected source spectra and validated coadds remain pending.

Use **Search by RA / Dec** for coordinates. Choose a minimum epoch separation in
the toolbar, then **Highlight changes** for numbered residual markers and explanatory
captions. The comparison defaults to the first and last displayed epochs. The
Compare tab selects another pair. The timeline shows actual elapsed days.

See [the requirements review](REQUIREMENTS_REVIEW.md) for the mandatory objectives,
optional considerations, cadence interpretation, and remaining scientific work.

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
