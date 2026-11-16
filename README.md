# SKYFRAME OBSERVATORY

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

## Explore and measure

- Enter decimal or sexagesimal RA/declination in Coordinates, or load a named
  target from Guide. Adjust the field size and select a detector or one of the
  102 calibrated channel windows.
- Play dated exposures, choose minimum epoch spacing, and find wavelength-matched
  comparisons. Analysis uses the full search independently of playback thinning.
- Use Highlight candidate changes for provisional residual rings, arrows, and explanatory
  captions tied to the actual supporting epochs.
- Click a visible source, then open Science. Measure native-pixel aperture light
  curves with statistical errors, inspect wavelength-by-time coverage, or request
  a deeper six-detector aperture spectrum. Blank coverage and rejected exposures
  are reported explicitly.
- Under Image processing, generate inverse-variance channel stacks with outlier
  rejection, PSF-aware differences, reference-star-corrected motion fits, and
  motion-compensated stacks. Significance images accompany processed results.
- Use Sky atlas to navigate IRSA's real 102-layer SPHEREx DR1 HiPS mosaic, then
  select a field for dated-exposure analysis. The mosaic combines observation times.
- Save completed analyses to Evidence & review. Reopen recorded settings through
  the page URL, rerun them, export CSV/JSON, and record local browser assessments.
  Notebook PDF reports embed the complete evidence JSON.

The default playback spacing is 30 days. Available choices are all exposures,
1, 30, and 180 days. The challenge's six-month survey description specifies no
mandatory animation interval. Playback speed controls time on screen separately.

## Processing and data access

Public SPHEREx DR1/QR3 SIA searches and FITS cutouts use anonymous IRSA access.
Gaia DR3 overlays and counterpart checks use Harvard VizieR, ESA TAP, and ARI
providers, with a persistent 15-minute cone-search cache and shared in-flight
requests. Cached catalog rows remain available during provider outages, with
retrieval dates and provider names displayed. Positions use linear proper-motion propagation from
the catalog epoch. External services can time out and their errors remain visible.
No API key is required for these services.

During IRSA discovery outages, previously saved searches remain usable and show
an explicit stale-data warning. Equivalent coordinate formatting shares a search.
Field-size changes can reuse discovery metadata at the same center and download
new native cutouts. When dated images cannot be queried, coordinate searches open the real SPHEREx
all-sky mosaic. Saved observation fields support playback and candidate highlighting.
Search retries have a 25-second total budget and respect Retry-After. Repeated
failures defer uncached batch downloads while allowing cached inputs to proceed.

The viewer retries transient image failures, offers manual retry, and waits for
the current exposure to load before advancing playback. Gaia failures stay in the
catalog panel. Catalog overlays and counterpart queries use manifest dates and
can run independently of the FITS cutout service. Corrupted FITS cache entries
are detected by checksum and downloaded again.

The new `/api/science/jobs` endpoint accepts analysis requests, returns progress,
and supports subscriber-aware cancellation and duplicate-request sharing. Jobs
inspect up to 256 detector/time-balanced exposures. Image stacks use at most 64
compatible inputs. Limits and omitted inputs are included in result warnings.
Existing `/api` and `/v1` endpoints remain available for existing callers. Legacy
quick-look subtraction, coadds, and surface-brightness spectra retain their own
processing methods. The Science workspace uses the new processing pipeline.

Aperture photometry measures calibrated MJy/sr pixels on their native grid and
converts the flux to mJy using the local WCS pixel area. It propagates native
variance and sigma-clipped local-sky uncertainty. Source-mask pixels are retained
inside the aperture and excluded from the 1.5–4 aperture-radius sky annulus.
Measurements require at least 90% valid aperture coverage and 12 usable sky pixels.
PSF aperture losses and calibration systematics remain additional uncertainties.

New differences use shared-grid registration, isolated-reference-star offsets,
empirical PSF cross-convolution when enough stars exist, robust photometric scaling,
and constant or planar background correction. Variances propagate through squared
interpolation/convolution weights. Interpolation correlations and calibration
systematics remain additional. Motion fits use PSF/SNR errors with an assumed
0.5-arcsec astrometric floor and require independent validation.

Source wavelengths use the FITS approximate spectral WCS and official bundled
channel windows. Sparse samples can combine different dates. Complete channel
coverage, PSF-corrected spectra, and independently confirmed target detections
require further scientific validation. The requirements review records the actual
checks and remaining limits. [Requirements review](REQUIREMENTS_REVIEW.md)

## Local storage

Set `SPHEREX_DATA_DIR` to keep an existing cache. The default is `backend/data`.
Search snapshots, FITS cutouts, previews, and `evidence.sqlite3` live there and are
ignored by Git. Idle downloaded FITS and generated previews can be evicted within
the configured budget. Active analysis frames are pinned. Search manifests,
reports, and saved evidence are preserved. Run one backend process per cache.

Jobs and their short-lived results live in memory. Saved evidence and assessments
persist in SQLite. Review counts represent browser-local assessments. Saved
measurements retain FITS checksums, observation/release IDs, processing parameters,
library versions, software SHA256, and the calibration SHA256. Regenerating an
image after cache eviction can require archive access.

## Validation

```powershell
uv run --project backend pytest backend/tests -q
uv run --project backend ruff check backend/src backend/scripts backend/tests
cd frontend
npm ci
npm run lint
npm run build
npm run test:science
npx playwright install chromium
npm run test:e2e
```

GitHub Actions runs backend tests/lint, frontend lint/build, motion-stack tests,
and critical browser regressions. Browser fixtures are separate from opt-in live
archive checks. Run `uv run python scripts/validate_live.py --frames-per-target 2`
from `backend` for all five challenge fields. Live reports are saved in the data
folder. The browser tests use a separate temporary cache.

Public-domain deployment is outside the current task. The app runs locally from
one FastAPI URL. The team’s charcoal-and-gold interface is retained.

Detailed archive information is available in the backend README and build plan.
[Backend README](backend/README.md) · [Build plan](backend/BUILD_PLAN.md)

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

## Shift & Stack

Open **Shift & Stack** in the navigation, or go to `/?view=shift-stack`.
Compare four archived SPHEREx 3I/ATLAS exposures with the stars held fixed,
with the comet centered at its published IRSA position, or along a trial path.
Both previews use the same brightness stretch. The practice hunt adds a
simulated source to a nearby real SPHEREx field and ranks 81 trial paths using
two exposures. It reports the winning path's contrast on the remaining two.

The compact, bundled quick-look cutouts use QR2 detector 5, a common sky grid,
a median background per frame, and a 0.0025 MJy/sr storage step. Original FITS
files and their wavelengths are available in the app. The aligned view mixes
nearby wavelengths and is intended for visualization.
[IRSA's 3I/ATLAS dataset](https://irsa.ipac.caltech.edu/data/SPHEREx/docs/comet3iatlas/index.html)

To regenerate the images, run `uv run python scripts/build_comet_demo.py`
from `backend`. From `frontend`, run `node --test tests/motionStack.test.mjs`
with Node 24 to check the real comet recovery and the practice scan.


## Available actions during discovery outages

The app checks live discovery availability once per minute. During an outage it
hides live refresh, live detector/channel filtering, and deeper six-detector
queries. A saved-field selector opens dated data that are already available.
Uncached coordinates open Sky atlas with a clear combined-time mosaic label.
Temporal-analysis controls appear when dated exposures are loaded.

The toolbar and discovery panel use **Highlight candidate changes**. This action
compares matched epochs and annotates provisional motion or brightness residuals.
The atlas selector offers its 100 published layers. Blank dichroic mosaic channels
51 and 52 are excluded. Native spectral calibration retains all 102 channels.


The five NASA challenge targets include bundled, dated IRSA discovery metadata.
This allows a fresh installation to request their real spectral images while
live discovery is unavailable. Images download from IRSA and retain their actual
observation dates and quality flags. The interface displays the original
metadata retrieval date and the live-discovery availability state.
