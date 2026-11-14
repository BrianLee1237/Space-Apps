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
| Six-detector coadds | Detector selection works. Combining observations into validated weighted coadds remains pending. |
| Spectral fingerprint | Clicking an image samples up to 16 exposures in that detector sequence. Native 3×3-pixel mean surface brightness, variance-derived uncertainties, zodiacal subtraction, wavelength, and dates are returned. Full-band, PSF-corrected source spectra remain pending. |
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
