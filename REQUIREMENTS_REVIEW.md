# Challenge requirements and current behavior

Reviewed against the challenge text supplied in this project conversation on November 14, 2026.

## Required experience

| Requirement | Implemented behavior | Verification limit |
| --- | --- | --- |
| Enter RA and declination | Visible search button and coordinate controls open by default. Decimal and sexagesimal input. | Browser build and request contract checked. |
| Retrieve real SPHEREx images | Anonymous IRSA DR1/QR3 search, FITS cutouts, WCS-aligned previews. | Coverage and quality depend on archive observations. |
| See change over time | Playback with all exposures or minimum epoch separations of 1, 30, or 180 days. Real elapsed days appear on the timeline. | Epoch mode chooses individual exposures. |
| Test the five named targets | Guided targets resolve to documented fields. Their archive retrieval has been tested. | Retrieval does not establish that all five show detectable motion or variability. |
| Public-facing web tool | Frontend and API run together locally. | Public hosting remains to be configured. |

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

Use **Highlight changes** after loading at least two epochs. The default comparison
spans the first and last displayed epochs. The Compare tab can select another pair.
Detections appear as numbered rings with short captions. Paired positive and
negative residuals also have directional arrows. Selecting a marker opens its
caption, comparison dates, elapsed days, and measured displacement or residual.

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
| Spectral fingerprint | Brian’s extraction samples up to six temporal groups per detector across all six detectors. Each native-pixel measurement includes wavelength, uncertainty, flags, and date. The scatter plot shows uncertainty bars and hover details. Complete channel coverage and PSF-corrected source spectra remain pending. |
| Subtraction | Common-grid differences and residual detection work. PSF matching, robust photometric/background matching, and full uncertainty propagation remain pending. |
| Field of view | Continuous 0.5–60 arcmin backend coverage and frontend selection. |
| Gaia DR3 | Catalog overlays with linear proper-motion propagation. Parallax and radial-velocity propagation remain pending. |
| Contamination flags | Selected-frame metadata is retrieved on demand with decoded flags, wavelength, and PSF width. |
| Shareable coordinates | RA, declination, field size, detector/channel selection are stored in the URL. Epoch spacing currently uses local UI state. |

The official spectral calibration table bundled as `channels.json` was extracted
from `SPECTRAL_CHANNELS` in the following public calibration product. Its wavelength
windows are used with each cutout's approximate spectral WCS for display filtering.
[Calibration FITS](https://irsa.ipac.caltech.edu/ibe/data/spherex/qr3/spectral_channels/cal-sch-v2-2026-229/spectral_channels_spx_cal-sch-v2-2026-229.fits)

IRSA documents the spectral WCS lookup as suitable for visualization. Quantitative
analysis should use the high-fidelity wavelength calibration and appropriate
spectral-response and PSF treatment. [SPHEREx data products](https://caltech-ipac.github.io/spherex-archive-documentation/spherex-data-products/)

## Integration verification

All five guided targets returned real detector-6 observations and valid PNGs from
both endpoints of their available time range during this integration. Counts were
59 for Barnard’s Star, 96 for Epsilon Indi B, 45 for WISE 0855, 56 for RW Aurigae,
and 91 for R Draconis. These counts describe cached archive searches at the test
time and can change as the archive grows.

WISE 0855 also returned two captioned residual candidates, working coadd and
difference PNGs, and 36 dated spectral measurements spanning approximately
0.762–4.968 µm. One transient cutout failure was skipped and reported in the
spectrum warnings. Channel 101 returned five exposures within its calibrated
4.9304–4.9724 µm window.

The integration passed 21 backend tests, Python lint, and the production frontend
build. Browser checks passed coordinate entry, URL loading, epoch filtering,
caption placement, playback, difference rendering, coadd rendering, metadata,
mobile overflow checks, and invalidation of a delayed comparison after changing
its selected pair. No browser runtime errors were recorded. Frontend lint reports
six advisory warnings about Fast Refresh exports and state updates in effects.
