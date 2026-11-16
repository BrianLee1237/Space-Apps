# Challenge requirements and current behavior

Reviewed against the challenge text supplied in this project conversation on November 15, 2026.

## Required experience

| Requirement | Implemented behavior | Verification limit |
| --- | --- | --- |
| Enter RA and declination | Coordinates button and coordinate controls open by default. Decimal and sexagesimal input. | Coordinate entry, URL loading, and production browser flow checked. |
| Retrieve real SPHEREx images | Anonymous IRSA DR1/QR3 search, FITS cutouts, WCS-aligned previews. | Coverage and quality depend on archive observations. |
| See change over time | Playback with all exposures or minimum epoch separations of 1, 30, or 180 days. Real elapsed days appear on the timeline. | Epoch mode chooses individual exposures. |
| Test the five named targets | Guided targets resolve to documented fields. All five returned real images in the November 15 live checks. | Retrieval does not establish that all five show detectable motion or variability. |
| Public-facing web tool | Frontend and API run together locally. Docker packaging and deployment instructions are present. | Public HTTPS hosting and external-device verification remain pending. |

## Cadence

The supplied challenge describes mapping the sky every six months. It requests a
series of images displayed like a video and specifies no mandatory frame duration
or fixed separation between images. Actual exposures have irregular spacing.

The default minimum separation is now 30 days. Users can choose every exposure,
at least one day, at least 30 days, or at least 180 days. The first available
exposure starts each sequence and subsequent exposures are selected only when
the chosen minimum interval has elapsed. Missing epochs are omitted. Playback
speed controls screen time independently from observation time.

## Visible change analysis

Use **Find changes** after loading at least two epochs. The current API analyzes
up to three disjoint, wavelength-compatible epoch pairs. Captions include the
number of supporting pairs. Numbered rings identify residuals and paired positive
and negative residuals can have directional arrows.

The November 15 fix makes a successful scan advance playback to the first
candidate's later observation. Each candidate is displayed on its own later epoch.
Difference overlays require the candidate's actual comparison dates to match the
selected difference pair. Selecting a candidate opens its evidence epoch and
explanation. Playback and manual stepping exit the before/after view, and a new
source selection invalidates pending motion results.

Candidate captions describe image evidence and retain an unverified label. A
two-image residual can arise from motion, variability, spectral sampling, the
PSF, or detector artifacts. A zero-result scan displays zero candidates and its
warnings. The software does not create example detections when none pass its
thresholds.

## Optional considerations in the challenge

| Feature | Current behavior / remaining work |
| --- | --- |
| Latest releases | Configurable DR1/QR3 collections, cached search snapshots and refresh through the API. |
| 102 channels | All 102 calibrated wavelength windows are selectable. Frames are filtered by center wavelength and pixels outside the chosen window are masked. These quick-look windows differ from geometric channel-map assignments and full mosaics. |
| Six-detector coadds | Aligned unweighted mean coadds work for distinct observations. Streaming accumulation and half-coverage masking are implemented. PSF matching, outlier rejection, and inverse-variance weighting remain pending. |
| Spectral fingerprint | Image clicks reuse up to 24 cached native FITS exposures from the current search. This fast preview can cover one detector. The broader API path supports six-detector sampling. Samples include wavelength, uncertainty, flags, and date. Complete channel coverage and PSF-corrected source spectra remain pending. |
| Subtraction | Common-grid subtraction includes a robust constant background correction and Gaussian PSF homogenization when both input headers provide PSF_FWHM. Empirical PSF kernels, photometric scaling, spatial background models, and propagated difference uncertainty remain pending. |
| Field of view | Continuous 0.5–60 arcmin backend coverage and frontend selection. |
| Gaia DR3 | Brightness-limited catalog overlays use ESA with an ARI mirror fallback and cached cone searches. Linear proper-motion propagation works. Parallax and radial-velocity propagation remain pending. |
| Contamination flags | Selected-frame metadata is retrieved on demand with decoded flags, wavelength, and PSF width. |
| Shareable coordinates | RA, declination, field size, detector/channel selection are stored in the URL. Epoch spacing currently uses local UI state. |

The official spectral calibration table bundled as `channels.json` was extracted
from `SPECTRAL_CHANNELS` in the following public calibration product. Its wavelength
windows are used with each cutout's approximate spectral WCS for display filtering.
[Calibration FITS](https://irsa.ipac.caltech.edu/ibe/data/spherex/qr3/spectral_channels/cal-sch-v2-2026-229/spectral_channels_spx_cal-sch-v2-2026-229.fits)

IRSA documents the spectral WCS lookup as suitable for visualization. Quantitative
analysis should use the high-fidelity wavelength calibration and appropriate
spectral-response and PSF treatment. [SPHEREx data products](https://caltech-ipac.github.io/spherex-archive-documentation/spherex-data-products/)

## November 15 verification

Pulled main at `63941da`, including Rafael's `19907b4` science upgrade. All five
guided targets returned real detector-6 observations and valid PNGs from both
endpoints of their available time range. Counts were 59 for Barnard’s Star,
96 for Epsilon Indi B, 45 for WISE 0855, 56 for RW Aurigae, and 91 for R Draconis.
These counts describe archive searches at the test time and can change.

For WISE 0855, the default 30-day playback filter selects four epochs. Matching
those four returned one compatible pair. Matching a time-distributed sample of
24 underlying exposures returned the API's maximum 12 ranked pairs. Matching and
discovery currently inspect the playback-filtered sequence. This loses useful
comparison opportunities and should be improved by selecting scientifically
compatible observations before thinning for playback.

The matched-pair discovery request returned six unverified residuals. A browser
regression check reproduced zero visible markers on the initial frame. The fix
advances to the evidence epoch, where all six markers are visible. Stepping to an
unrelated epoch hides them. This establishes annotation behavior, with target
identification and validated motion/variability demonstrations still pending.

Validation passed 32 backend tests and the frontend production build. Browser
checks passed coordinate URL loading, playback, wavelength matching, before/after
interaction, automatic annotation epoch selection, annotation hiding, switching
from before/after to playback, PDF download, and mobile overflow checks. The PDF
export produced a 70,976-byte file with a PDF header. No browser runtime errors
were recorded during these checks.

Python lint currently reports 24 style findings, comprising 21 long lines and
three import-order issues. Frontend lint reports seven advisory warnings about
Fast Refresh exports and state updates in effects. The unit tests emit one
Starlette/httpx deprecation warning. Container execution and public deployment
have not been verified during this review.

## Highest-priority remaining work

- Complete public HTTPS hosting, persistent cache configuration, request limits,
  and an external-device test.
- Select wavelength-compatible observations from the full search before temporal
  thinning. Build comparable per-epoch coadds and propagate variance.
- Validate source identity and expected behavior on the five targets. Include
  observed non-detections and uncertainty when the data cannot establish a change.
- Add light curves with source/background photometry and uncertainty. The current
  motion tracker associates image peaks and lacks validated astrometric errors.
- Improve quality ranking to distinguish informational flags from artifact flags.
  Associate repeated residuals using astrometry and PSF scales instead of only a
  fixed 40-arcsec positional box.
- Add background jobs, shared-request deduplication, progress, and managed temporary
  caching for expensive queries. The current cache raises a capacity error when full.
- Expose a clearly labeled cached spectral preview and an explicit deeper
  extraction request. Integrate official spectrophotometry where appropriate.
- Include time spacing, selected observations, processing parameters, and software/
  calibration versions in shareable evidence records.
- Add continuous integration for unit tests, production builds, lint, and critical
  browser paths. Resolve the remaining lint findings.
