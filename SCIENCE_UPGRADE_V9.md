# V9 science & workflow upgrade

Preserves the existing SPHEREx viewer, 3D RA/Dec selection, time-lapse, six-detector/channel selector, notebook, Gaia overlay, and quick-look FITS endpoints.

## New user journeys

1. **Compare → Find comparable epochs.** The backend downloads/reads real FITS metadata and ranks same-detector epochs with center wavelengths within 1.2% (at least 0.012 µm). Select the matched pair for a before/after slider, then generate a difference image. Raw comparisons of unmatched wavelengths remain visibly caveated.
2. **Motion.** In an **actual observation image** (not the 3D navigation sphere), click a visible source. Open Motion and choose Track selected source. Registered actual FITS pixels are sampled across wavelength-compatible frames; missing/low-confidence matches are omitted. The displayed displacement is apparent **unverified image-centroid movement**, *not measured physical proper motion*. No catalog ID or discovery confirmation is inferred.
3. **Discover.** Process up to three disjoint, wavelength-matched epoch pairs sampled across the available timeline. Residuals only appear if produced by the existing science algorithm. Multiple-pair support is experimental and not a false-positive probability.
4. **Guide.** Start with any of the five documented NASA challenge targets and follow the buttons to Compare, Discover, Motion and Notebook. All dates and measurements appear only when retrieved.
5. **Notebook → Export PDF.** A browser-generated report contains actual observation IDs, dates, noted coordinates, quality warnings and (if the browser can retrieve them) the real preview images. When previews are unavailable the PDF explicitly records their absence.
6. **Public hosting.** `Dockerfile` and `DEPLOY.md` let a teammate configure one hosted URL; no deployment is performed automatically.

## Important caveats

- Wavelength matching uses the **center wavelength**, not per-pixel bandpass matching; PSF is smoothed only if both FITS headers expose valid `PSF_FWHM`. Difference images also remove a robust constant sky-background offset. **Not calibrated difference photometry**.
- Simple coadds still do not have cosmic-ray rejection or matched PSFs; see existing backend warnings.
- Gaia DR3 is an optical catalog of known positions, **not** object detections in the infrared image. Its default overlay is limited to 75 brightest catalog sources, and no discoveries are automatically confirmed.
- The baseline project is still responsible for authentic NASA archive availability, correctness of metadata, and applicable NASA challenge submission requirements.

## Automated verification

Backend: `cd backend && uv sync --locked && uv run pytest -q` (four new regression tests in `backend/tests/test_science_and_api.py`).
Frontend: `cd frontend && npm ci && npm run build`. Manual smoke-test the 3D coordinate picker, image click → Motion, time matching, before/after slider, Discovery, and a PDF export.
