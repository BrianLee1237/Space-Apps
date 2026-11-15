# SPHEREx Sky API

A Python backend for discovering SPHEREx observations at ICRS coordinates, retrieving
small multi-extension FITS cutouts, inspecting their wavelength and quality metadata,
and generating aligned PNG frames for a future sky animation viewer.

The implementation uses FastAPI, Astropy, HTTPX, NumPy, SciPy, and Pillow. Python 3.12
and a project-local virtual environment are installed in this working copy. `uv.lock`
records the resolved dependencies.

## Run locally

From this directory in PowerShell, run the following commands.

```powershell
uv sync --locked
uv run uvicorn spherex_api.app:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000/docs> for the interactive OpenAPI interface.
<http://127.0.0.1:8000/health> checks the local service. Archive availability is checked
by an actual search.

No NASA API key, IRSA login, AWS account, or paid astronomy API is needed for this
backend's public HTTPS searches and downloads. Live testing records the upstream
responses in `data/reports/live-validation.json`.

## Retrieve a field

This example searches the WISE 0855 challenge coordinates, reads the first frame's
metadata, and saves its FITS cutout and aligned preview.

```powershell
$base = 'http://127.0.0.1:8000'
$body = @{
    ra = '08h55m10.831s'
    dec = '-07d14m42.53s'
    fov_arcmin = 10
    collections = @('spherex_dr1', 'spherex_qr3')
    detectors = @(6)
} | ConvertTo-Json

$result = Invoke-RestMethod -Method Post -Uri "$base/v1/search" `
    -ContentType 'application/json' -Body $body
$result | Select-Object search_id, complete, frame_count, warnings

if ($result.frame_count -gt 0) {
    $frame = $result.frames[0]
    Invoke-RestMethod -Uri ($base + $frame.links.metadata)
    Invoke-WebRequest -Uri ($base + $frame.links.fits) -OutFile 'wise0855.fits'
    Invoke-WebRequest -Uri ($base + $frame.links.preview) -OutFile 'wise0855.png'
}
```

Decimal RA values and decimal strings use degrees. Sexagesimal RA strings use hours.
Declination uses degrees. This GET URL supports bookmarking and embedding coordinate
queries in another project.

```text
http://127.0.0.1:8000/v1/search?ra=133.79512917&dec=-7.24514722&fov_arcmin=10&detectors=6
```

Use repeated query parameters for multiple detectors or collections, such as
`detectors=4&detectors=6`. POST accepts arrays. Optional `mjd_min` and `mjd_max` constrain
UTC observation times. `max_records` defaults to 10,000 and supports up to 20,000
upstream rows. Detector filtering happens after that upstream limit. The manifest's
`complete` field reports possible truncation before filtering.

`fov_arcmin` is the full square width and supports 0.5 to 60 arcminutes. The default
`coverage="center"` searches a one-arcsecond circle around the requested center, using
the small-region pattern in the archive tutorials. `coverage="field"` searches a
circle enclosing the entire requested square. This includes observations covering
only the outer field and can take longer. Both modes retrieve cutouts padded for
detector rotation. Edge observations can have incomplete coverage or cutout errors.

## API routes

| Route | Result |
| --- | --- |
| `GET /health` | Local process health |
| `GET /v1/capabilities` | Supported collections, limits, and implemented products |
| `GET /v1/targets` | The five challenge fields and coordinate provenance |
| `GET` or `POST /v1/search` | Chronological observation manifest and per-frame links |
| `GET /v1/searches/{search_id}` | Saved immutable search snapshot |
| `GET /v1/searches/{search_id}/frames/{frame_id}` | Retrieve a cutout and return scientific metadata |
| `GET /v1/searches/{search_id}/frames/{frame_id}/fits` | Original archive cutout with all supplied HDUs |
| `GET /v1/searches/{search_id}/frames/{frame_id}/preview.png` | Common-grid, north-up, east-left PNG |

Searches cache for 15 minutes. `?refresh=true` runs a fresh archive query and creates
a new snapshot. Existing snapshots remain addressable. Frames download on demand,
with a cache key incorporating their upstream URL, sky center, and cutout size.

Preview options include `pixels=256` with a supported range of 32 to 1,024 pixels,
`subtract_zodi=true`, and `reject_bits=<unsigned bitmap>`. Supply both `vmin` and `vmax`
in the native surface-brightness units for a consistent display across epochs.
The default stretch uses each frame's own 1st and 99.5th percentiles. Brightness
comparisons need common limits. The PNG response headers record the limits, valid
coverage fraction, orientation, asinh stretch, and zodiacal subtraction setting.

## Data interpretation

The server selects `IMAGE`, `FLAGS`, `VARIANCE`, `ZODI`, and `WCS-WAVE` by their FITS
extension names. Downloaded cutouts retain additional extensions such as `EPSF`.
Metadata include the processing version, observation ID, detector, observation MJD,
file SHA-256, pixel flags, valid-pixel statistics, PSF width when supplied, and
approximate wavelength and bandwidth at the requested center.
Flag names and descriptions come from the downloaded `FLAGS` header, and the
metadata decode the flags active at the requested center.

SPHEREx uses linear variable filters. Wavelength changes across a detector and
between observations of the same source. The metadata distinguish detector-wide
wavelength coverage from the wavelength at the field center. Wavelength coordinates
use the alternate spectral WCS with SIP distortion disabled as in the IRSA tutorials.
Full spatial SIP remains enabled for sky registration.

All PNGs for a search use the same ICRS tangent-plane projection. The renderer uses
bilinear interpolation and makes unsupported pixels transparent. Interpolation
changes noise correlations. Quantitative photometry and uncertainty propagation
should use the FITS data and a validated measurement pipeline.

`ZODI` is a modeled background supplied separately from `IMAGE`. Raw downloads preserve
both. The preview subtraction option changes display processing and records that
choice. Pixel flag counts remain available even when the display excludes selected
bits. Inspect the flag definitions provided with each data release before choosing
a rejection mask.

Coordinates in the presets are documented fixed field centers. Barnard's Star and
Epsilon Indi B use larger fields to accommodate proper motion. Proper-motion and
parallax propagation, detection significance, saturation assessment, and confirmation
of motion or variability remain scientific validation tasks.

## Configuration and storage

The configuration variables can be set in the shell before launching the server.
`.env.example` documents them. The application reads the process environment directly.

| Variable | Default | Purpose |
| --- | --- | --- |
| `SPHEREX_DATA_DIR` | `./data` | Manifest and FITS cache directory |
| `SPHEREX_TIMEOUT_SECONDS` | `120` | HTTP read timeout per attempt |
| `SPHEREX_CACHE_BUDGET_MB` | `2048` | Aggregate local cache budget |
| `SPHEREX_CORS_ORIGINS` | Empty | Comma-separated frontend origins |

Archive requests have a four-request concurrency bound per application process,
up to two retries for transient errors, and a 32 MiB response limit. Downloads are
validated before atomic publication. File locks prevent duplicate writes across
threads and local processes. The cache returns HTTP 503 when its budget is reached.
Move or remove expendable generated data when you choose to reclaim space.

An archive error returns HTTP 502 with a description. A result truncated by IRSA
returns `complete=false` and a warning. Invalid coordinates or display parameters
return HTTP 422. Unknown searches or frames return HTTP 404.

This working copy runs on localhost. A public deployment can add shared storage,
request admission/rate limits, and a background job queue for lengthy searches or
bulk frame preparation. Those components can use the same manifest and frame API.

## Verify

```powershell
uv run pytest -q
uv run ruff check src scripts tests
uv run python scripts/validate_live.py --frames-per-target 2
```

The offline regression checks cover coordinate validation, VO errors and overflow,
named FITS extension selection, wavelength units, rotated-sky registration, concurrent
cache access, PNG generation, failed-download cleanup, and the cache budget.

The opt-in live script searches all five challenge fields and attempts the earliest
and latest available detector-6 frames. It writes a JSON report and PNGs under
`data/reports`. `--target wise-0855` selects one field. `--refresh` bypasses search
caching. Live results demonstrate archive access and frame processing. Measuring
the expected astrophysical motion or variability needs further analysis.

The data-access research, review of your notebooks, and proposed next stages are in
[BUILD_PLAN.md](BUILD_PLAN.md).

## Existing frontend integration

The `/api` adapter matches `frontend/src/services/api.ts` without changing that
frontend. `/api/resolve` resolves the guided targets. `/api/observations` accepts
`ra`, `dec`, `fov`, `mode`, and `index`, and returns the existing observation schema.
Auto chooses detector 6. Detector mode accepts 1 through 6. Image URLs point to
`/api/images/{search_id}.{frame_id}.png` and use one brightness scale across the
sequence. The adapter includes actual cached quality metadata and prepares the
first frame before returning a sequence.

After `npm run build` in `frontend`, restarting FastAPI mounts `frontend/dist` at
the root URL. Existing `/v1` APIs and `/docs` remain available. `/api/difference`
and `/api/difference.png` implement the Compare tab: both requested observations
are resampled with bilinear interpolation onto one shared tangent-plane grid and
subtracted (to minus from), rendered as a zero-centered red/blue PNG. `/api/overlays`
implements the Gaia DR3 toggle: a cone search against ESA's public Gaia Archive
TAP+ `sync` endpoint (`gea.esac.esa.int`, no key needed), with each source's
position linearly propagated by its own proper motion to the observation's
epoch and projected onto the same output grid `/api/images` renders. `/api/candidates`
implements the Discover tab (`candidates.py`): differences the earliest and
latest of the given observations, subtracts a local median background to
suppress field-wide zodiacal/flat-fielding mismatches, erodes a few pixels in
from each frame's resampled edge (differently-rotated detectors don't share a
valid-pixel boundary), and flags blobs that clear a 10-sigma threshold at
roughly a PSF-sized footprint. Paired brightened/dimmed blobs become
`moving-source` candidates; unpaired ones become `brightness-change`. Pixels
carrying an implausibly large raw difference (detector overflow near a
bright/saturated star, not real linear flux) are excluded rather than
reported. This is a best-effort statistical screen, calibrated empirically
against this project's own guided targets, not a validated discovery
pipeline.

`mode=channel` on `/api/observations` uses the official calibration windows in
`channels.json`. A bounded two-worker inspection reads the FITS spectral WCS at the
requested position. Frames qualify by their center wavelength, and PNG rendering
masks pixels outside the chosen window. Detector-wide SIA wavelength bounds cannot
identify the wavelength at an individual sky position. Unavailable cutouts produce
partial-coverage warnings. An entirely failed retrieval returns an archive error.

`/api/metadata?observationId=...` returns decoded center flags, center wavelength,
bandwidth, and PSF FWHM after the FITS cutout is inspected. Older cached metadata
are refreshed using the metadata schema version.

`/api/combine` averages distinct input exposures on the first input's shared grid.
`imaging.combine_registered` streams sums and valid-pixel counts, requiring the
ceiling of half the input count for retained pixels. Warnings describe differing
fields, detectors, spectral sampling, and the limits of an unweighted mean.

`/api/spectrum` accepts either `ra`/`dec` or an `observationId` with fractional
`x`/`y`. Pixel selection is inverted through the preview's common WCS. The service
searches all six detectors and samples up to six temporal groups per detector.
Native-pixel flux, variance-derived uncertainty, measured wavelength, decoded
quality flags, and observation date are returned. Artifact-flagged pixels are
skipped. Downloads are paced and transient failures are counted in warnings.
This sparse, multi-epoch surface-brightness fingerprint requires further photometric
and spectral-response treatment for quantitative source analysis.
