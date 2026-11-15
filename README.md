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
a quick-look subtraction that retains calibrated surface-brightness input units,
with no PSF matching or photometric/background fitting. The response describes
these limits in its `warnings`. The two frames are reordered into true
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

Channel selection uses the bundled official 102-channel calibration windows.
`mode=channel&index=1-102` chooses the associated detector, inspects the actual
FITS spectral WCS at the requested position, and includes exposures whose center
wavelength falls within that window. Preview pixels outside the window are masked.
This quick-look selection uses approximate spectral WCS. Empty coverage is shown
explicitly. [IRSA spectral calibrations](https://irsa.ipac.caltech.edu/Missions/spherex.html)

Exposure combination is implemented through `/api/combine?ids=...`. It averages
aligned real exposures using streaming sums and valid-pixel counts, keeping pixels
covered by at least half the distinct inputs. This is an unweighted mean with
quality-bit masking available through the API. Warnings describe mixed detector
bands, variable wavelength, and blurring of moving sources. The UI combines the
currently displayed epochs.

Clicking an image or a candidate requests `/api/spectrum`. Brian's six-detector
extraction is retained, with up to six temporally distributed samples per detector.
Each point includes its actual native-pixel wavelength, surface brightness,
variance-derived uncertainty, quality flags, and observation date. Invalid and
artifact-flagged pixels are skipped. The plot shows individual samples with error
bars and hover details. Coverage depends on the available exposures, and dates
can differ across samples. PSF-fit photometry and complete 102-channel spectra
remain future work.

Wavelength can vary between exposures within one detector. Use the
wavelength metadata from the `/v1` API when assessing motion or variability.

Search snapshots and FITS files are stored under `backend/data` and are ignored by
Git. The Python environment and generated frontend build are also ignored. The
frontend retains the team’s navigation and components with an integrated charcoal-and-gold visual system.

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

## Integrated branch review

Reviewed `main`, `brian-branch-rq`, `rafael`, and `feature/frontend` on November 14,
2026. Main already included Brian's channel/coadd/spectrum work and Rafael's
navigator redesign. The older frontend branch contains the original frontend on
an unrelated Git history. Its components are represented in the integrated app.

The final integration restores coordinate controls, 1/30/180-day epoch spacing,
change captions and arrows, and on-demand wavelength/quality metadata. It connects
the 3D navigator to the archive search and protects asynchronous comparison results
against changes of field, epoch selection, and display mode. See
[the requirements review](REQUIREMENTS_REVIEW.md) for scientific and hosting limits.
