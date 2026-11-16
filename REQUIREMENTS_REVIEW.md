# Challenge requirements and current behavior

Reviewed against the supplied challenge on November 15, 2026. Public hosting is
excluded from the current implementation request.

## Required experience

| Requirement | Current implementation | Verification and limits |
| --- | --- | --- |
| Enter RA and declination | Visible Coordinates control, decimal/sexagesimal parser, coordinate URLs | Browser and API checks pass |
| Real SPHEREx images | Anonymous IRSA DR1/QR3 search, FITS cutouts, WCS-aligned previews | Live images retrieved for all five named fields |
| Video-like change viewing | Dated timeline, playback, adjustable spacing, shared display limits | Full-search analysis remains independent of temporal playback thinning |
| Test five targets | Guide includes Barnard’s Star, Epsilon Indi B, WISE 0855, RW Aurigae, R Draconis | Retrieval and fixed-position measurements are tested. Astrophysical identities and expected changes require independent confirmation |
| Public-facing tool | Browser frontend and API run together locally | Public hosting deferred by user |

## Cadence

The challenge describes a whole-sky survey every six months and requests images
played like a video. It gives no required frame duration or fixed epoch interval.
Exposures have irregular observation times. Playback offers all exposures or a
minimum gap of 1, 30, or 180 days, defaulting to 30. Speed sets screen time.
Analysis inspects the full search, with explicit workload limits, before selecting
same-detector, same-channel comparison data.

## Implemented improvements

| Feature | Behavior and limits |
| --- | --- |
| Change highlighting | Strong provisional residuals have rings, directional arrows where supported, and captions attached to supporting observation dates. Up to three disjoint compatible pairs support candidate association using sky positions and PSF scales |
| Light curves | Native fractional-aperture mJy flux, native variance and annular-background errors, per-channel scatter statistics, and CSV export |
| Wavelength-time coverage | Inverse-variance cells with scatter-inflated uncertainty, interactive channel selection, and blank missing coverage |
| Six-detector aperture spectra | Explicit deeper archive request across all six detectors, detector/time-balanced inspection of up to 256 exposures, flagged/invalid measurements omitted with warnings |
| Weighted stacks | Same-channel inverse-variance stacks, robust background correction, 5-sigma pixel rejection with at least three inputs, and half-input coverage threshold |
| Advanced subtraction | Reference-star offsets, empirical PSF cross-convolution when at least three usable stars exist per epoch, robust scaling, constant/planar background, variance propagation, and significance preview |
| Motion analysis | Weighted tangent-plane fit, centroid errors and assumed 0.5-arcsec floor, reference-star correction where supported, selectable east/north motion-compensated stacking |
| 102-channel atlas | On-demand Aladin Lite view of the real IRSA DR1 all-sky HiPS cube. Channels 51/52 are labeled blank dichroic layers. Click a sky position to load dated observations |
| Gaia DR3 | Brightness-limited overlay and nearby counterpart query, Harvard VizieR/ESA/ARI failover and persistent, shared 15-minute cache. Linear proper motion excludes parallax and radial velocity |
| Updated data | Configurable collections and Refresh archive control create new search snapshots |
| Work management | Two-worker analysis queue, bounded admission, progress, subscriber-aware cancellation and deduplication |
| Cache management | Idle FITS/preview eviction under the cache budget, active analysis pinning, preserved manifests/reports/evidence |
| Evidence | SQLite persistence, coordinate/source/epoch/observation URLs, JSON and CSV export, PDF with embedded JSON, processing parameters and calibration/software/FITS hashes |
| Local review | Saved evidence queue and replaceable per-browser assessments with explicit provisional classifications |
| Comet demonstration | Integrated branch provides real 3I/ATLAS exposures and predicted-path stacking. Practice mode explicitly labels its injected source |
| Regression checks | Backend tests/lint, frontend lint/build, scientific motion-stack checks, desktop/mobile browser tests, and GitHub Actions |

## Scientific interpretation

An image residual can arise from motion, variability, spectral response, PSF,
calibration, or detector artifacts. Candidate captions preserve provisional status.
No-data and zero-detection outcomes remain visible.

The approximate FITS spectral WCS and bundled channel windows support quick-look
comparison. Quantitative spectroscopy needs high-fidelity wavelength calibration,
spectral-response treatment, and PSF/aperture corrections. Spectral samples can
come from different dates. [IRSA data products](https://caltech-ipac.github.io/spherex-archive-documentation/spherex-data-products/)

Aperture fluxes have statistical errors but require aperture-loss and absolute
calibration treatment. Differences propagate independent-pixel variances through
resampling and convolution. Correlations/systematics remain additional. Motion
fits omit parallax/acceleration and use an assumed astrometric floor. Source
associations require validation against catalog positions and neighboring sources.

The atlas is a combined-time visualization product. Its layers cannot supply
dated motion measurements. IRSA documents blank dichroic layers and visualization
artifacts. [IRSA mosaic tutorial](https://caltech-ipac.github.io/irsa-tutorials/spherex-hipscube/)

## Live checks on November 15

All five detector-6 searches returned real frames and valid earliest/latest PNGs.
Archive counts were 59 for Barnard’s Star, 96 for Epsilon Indi B, 45 for WISE 0855,
56 for RW Aurigae, and 91 for R Draconis. Counts depend on query and archive updates.
The field centers are fixed documented coordinates. They do not provide moving
source ephemerides.

The new aperture API was also exercised on the two archived test exposures per
field. It returned two usable fixed-center apertures in the WISE field and zero
in each of the other four fields. The RW Aurigae samples carried OVERFLOW flags,
and R Draconis carried OVERFLOW, SUR_ERROR, and BLOOM. Other omissions failed
aperture/background quality coverage. These outcomes are recorded locally in
`data/reports/science-validation.json` and require source identification and
epoch-aware positions before interpreting target brightness.

The WISE 0855 field’s full-search matching returned 39 compatible pairs, improving
coverage over its four time-thinned playback epochs. A selected real field source
produced native aperture measurements, a six-detector spectrum, weighted stacks,
and propagated-variance differences. This selected source is a field source and
has no established identification as WISE 0855.

A too-small sky annulus initially rejected detectors 2 and 4 because their known
source masks extended into it. Expanding the outer annulus from 2.5 to 4 aperture
radii recovered valid measurements across all six detectors. Invalid exposures
continue to be rejected. Gaia GET retrieval succeeded on a Barnard field query,
while other live requests timed out at the external services. Catalog failures
are reported in the interface.

Scientific confirmation of expected motion/variability on the five named objects
remains pending. Coverage, fixed-coordinate aperture measurements, and residual
markers alone cannot establish those claims.

The test suite includes native-aperture scaling, source-mask background coverage,
squared interpolation weights, outlier rejection, injected motion recovery,
reference-star offsets, empirical PSFs, job cancellation/deduplication, evidence
persistence, cache protection, and API validation. Browser checks exercise full
search selection independently of playback, source selection, mobile layout,
live charts/exports, saved evidence reload, and atlas navigation.
The final local checks passed 57 backend tests, three scientific motion-stack
tests, and five browser regression tests, with clean backend/frontend lint and a
successful production build. A PDF parser verified its embedded evidence JSON.
The live atlas check confirmed exact channel-100 tiles and no browser runtime
errors after explicit channel-to-tile mapping replaced frequency interpolation.

## Remaining validation

- Identify and epoch-propagate each named moving target, quantify completeness and
  false positives, and compare recovered motion/variability against independent data.
- Validate the astrometric floor and correlated-noise/significance calibration.
- Add high-fidelity wavelength response, aperture corrections, and PSF-fit source
  photometry for quantitative spectra and crowded fields.
- Run a real external multi-user review study before interpreting assessment counts.

One Starlette/httpx test-client deprecation warning remains. The on-demand Aladin
bundle exceeds Vite’s size advisory. Public hosting and container execution have
been deferred and unverified in this task.


## Upstream reliability review

The current fixes preserve the latest Skyframe Observatory palette and branding.
Live checks reproduced IRSA SIA and TAP 502 responses, ESA connection timeouts,
and ARI read timeouts. Harvard VizieR returned genuine I/355 Gaia DR3 rows for the
active field. The API projected 43 markers, with the next epoch reusing the
persistent cone cache. The query records its provider and retrieval time.

IRSA FITS cutouts remained reachable during the metadata-service failure. A
live WISE-field request returned HTTP 200 and a valid multi-extension FITS image.
Saved discovery snapshots support existing fields and new field sizes at the
same center. Their original retrieval dates remain intact. Newly uncached sky
positions remain dependent on the external discovery service.

Regression tests cover concurrent/persistent Gaia caching, labeled stale catalogs,
stale search recovery, equivalent coordinate serialization, field-size cutout
regeneration, initial-cutout fallback, corrupted-cache repair, invalid upstream
FITS responses, Retry-After, bounded discovery retries, cancellation CORS, and
batch-download deferral. Browser tests cover catalog failure/recovery without
hiding the image, exposure-load-aware playback, and automatic image retry.
