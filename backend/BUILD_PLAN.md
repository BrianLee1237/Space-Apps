# Data access and implementation plan

Research checked on November 14, 2026. The requested first stage is a usable backend
for SPHEREx discovery and retrieval. The code and local cache are in this directory.

## SPHEREx access

IRSA currently recommends DR1 together with QR3. The backend defaults to their wide
survey collections and also accepts their deep-survey collections. It queries
SIA2 and requests spatial cutouts from the returned archive URLs. The release
selection is explicit in each manifest so that a future release can be introduced
with its own validation and provenance. [DR1 overview](https://irsa.ipac.caltech.edu/data/SPHEREx/docs/overview_dr1.html)

The SIA endpoint is `https://irsa.ipac.caltech.edu/SIA`. Its response provides
observation times, footprints, detector bandpasses, and access URLs. New images are
ingested weekly, with SIA availability potentially lagging ingestion by about a day.
The archive's TAP metadata interface is another supported route for recent arrivals.
The existing adapter uses SIA and records any query overflow. [Archive access guide](https://caltech-ipac.github.io/spherex-archive-documentation/spherex-data-access/)

IRSA's specialized cutout service preserves the MEF structure and WCS relationships.
Using it avoids fetching full detector images for a small sky patch. Each request
uses the returned URL plus `center`, `size`, and `gzip=false`. [Cutout service](https://irsa.ipac.caltech.edu/data/SPHEREx/docs/cutout_tool.html), [cutout parameters](https://irsa.ipac.caltech.edu/ibe/cutouts.html)

Public HTTPS access succeeded without account credentials during initial probing.
The IRSA cloud mirror also supports anonymous access, and may become attractive
for larger workloads. Its bucket is `nasa-irsa-spherex`. Cloud access is a later
adapter option because the current cutout path uses IRSA's on-premises service.
[IRSA cloud access](https://irsa.ipac.caltech.edu/cloud_access/)

The first larger-footprint SIA probes exceeded 25-second read timeouts. Small-position
queries returned results, including a 258-row DR1 response at the WISE 0855 position.
The API therefore exposes both center and full-field coverage modes. Center mode
is the default. This is an implementation choice based on the observed request
behavior and the small-position queries in the tutorials. Full-field queries remain
available for edge coverage.

## Scientific processing

The 102 nominal channels emerge from repeated LVF observations. Each individual
detector image carries spatially varying spectral information. A sequence grouped
only by detector can show spectral changes along with temporal changes. The current
API exposes wavelength metadata for frame selection. [Spectral-image tutorial](https://caltech-ipac.github.io/irsa-tutorials/spherex-intro/)

The named FITS planes provide the science image, variance, flags, and zodiacal model.
The wavelength WCS needs the lookup table retained in the HDU list. The current code
follows the tutorial's spatial and spectral WCS handling. Flag definitions can be
read from `MSKNnnnn` and `MSKDnnnn` header keywords. [Cutout tutorial](https://caltech-ipac.github.io/irsa-tutorials/spherex-cutouts/), [data-product documentation](https://caltech-ipac.github.io/spherex-archive-documentation/spherex-data-products/)

The next processing stages can build on the implemented archive adapter and manifests.

1. Prepare multi-epoch sequences using common wavelength intervals, output WCS,
   quality masks, and display limits. Record missing epochs and actual time gaps.
2. Build per-epoch, per-detector stacks with explicit spectral weighting. Establish
   variance propagation and coverage maps, then compare stacks with matched spectral
   sampling. Evaluate any temporal binning against moving-source smearing.
3. Adapt the pipeline's PSF-matching and background-fitting work to SPHEREx epochs.
   Validate subtraction on stationary stars, masked edges, injected moving sources,
   and known variable stars. Retain quantitative residual uncertainties.
4. Extract spectra with documented apertures or PSF photometry, backgrounds,
   uncertainties, spectral response, and quality flags. The archive's existing
   spectrophotometry service is a reference implementation to evaluate.
5. Connect the frontend to manifests, metadata, and shared-grid preview frames.
   Add playback, epoch selection, a common brightness scale, wavelength controls,
   and clear reporting of partial coverage.

IRSA also provides mosaic, source-discovery, and all-sky-cube resources. The cube
can help with context and spectral exploration. Time-resolved sequences should
retain individual observation timestamps and their contributing exposures.
[SPHEREx tools](https://irsa.ipac.caltech.edu/Missions/spherex.html), [source discovery](https://caltech-ipac.github.io/irsa-tutorials/spherex-source-discovery-tool-demo/)

## Review of your existing pipeline

The GitHub connection was used to inspect the repository and `spherex1.ipynb`.
The larger notebooks exceeded the connector's practical file response size, so
a shallow reference clone was downloaded to `%TEMP%/spherex-api-research/accretion-reference`.
The notebooks were inspected as JSON/code. [Your repository](https://github.com/vtattala/accreiton_notebook)

The inspected clone's commit is `d0a384372cfa2506177cb43d35440a5d1bd18d6b`.

| Notebook | Relevant work to adapt |
| --- | --- |
| `spherex1.ipynb` | Celestial WCS reprojection, overlap masks, initial SPHEREx/WISE residual displays |
| `spherex2.ipynb` | Moderate-source selection, image alignment, PSF broadening, aperture comparisons |
| `HOPS_383_pipeline_diagnostic.ipynb` | Pixel wavelength inspection, empirical PSFs, convolution kernels, robust scale factors, target photometry |
| `accretion.ipynb` | Candidate metrics, quality flags, forced apertures, classification and review products |
| `galactic_search.ipynb` | Archive discovery, cutout caching, background fitting, matched-filter significance, candidate consolidation |

The new service adapts the named-plane, WCS, finite-overlap, and provenance patterns.
The notebooks contain exploratory stages and machine-specific paths. Candidate
thresholds, cross-instrument scaling, PSF kernels, and background fits need validation
for a SPHEREx temporal sequence. The code also contains an explicit correction for
selecting `ZODI` accidentally as the science plane. A regression check now uses
shuffled extensions and a bright synthetic `ZODI` plane to catch that error.

WISE is allowed as a complementary layer under the supplied challenge instructions.
It can extend the temporal baseline and provide cross-identification. Cross-instrument
residuals need spectral-response and PSF treatment. The SPHEREx sequence can be
developed independently and then use the WISE work where it contributes.

## Other supplied resources

| Resource | Role and findings |
| --- | --- |
| [WiseView](http://byw.tools/wiseview) | Playback and citizen-science interaction reference. The supplied site returned HTTP 502 during research, so its current implementation could not be inspected. |
| [Gaia at MAST](https://archive.stsci.edu/missions-and-data/gaia) | Gaia DR3 can provide catalog context and proper-motion information. A future overlay should state its reference epoch and propagate coordinates to image epochs where appropriate. |
| [Aladin Lite](https://aladin.cds.unistra.fr/AladinLite/) | Candidate sky-navigation and catalog-overlay component for the frontend. Its catalog controls and coordinate-oriented interface were reviewed. |
| [CSA NEOSSat](https://www.asc-csa.gc.ca/eng/satellites/neossat/) | Separate telescope observations for a possible later moving-object demonstration. The core retrieval path uses SPHEREx. |
| [CADC](https://www.cadc-ccda.hia-iha.nrc-cnrc.gc.ca/en/) | Archives NEOSSat alongside other missions and provides additional search services. |
| [NEOSSAT tutorial](https://github.com/asc-csa/NEOSSAT_Tutorial) | Documents data retrieval, FITS inspection, and preprocessing. Reuse can be evaluated for a later NEOSSat adapter. |
| [NEOSSat dataset](https://data.asc-csa.gc.ca/dataset/neossat) | The supplied dataset landing page timed out on repeated checks. CSA's mission page confirms open astronomy data and links to the current portal and CADC. |

## Challenge-field validation

The presets use the supplied WISE 0855 position and documented CDS Sesame/SIMBAD
coordinates for the other four fields. They retain fixed centers and record their
sources. The larger Barnard's Star field accommodates motion relative to its catalog
position. Epsilon Indi B targets the brown-dwarf pair's field.

The live validation script records image counts, date coverage, detector counts,
cutout URLs, hashes, wavelength metadata, download results, and preview coverage.
Its earliest/latest sampling checks the data path. Demonstrating motion or measuring
variability will require wavelength-matched samples and science validation.

The November 14 run completed all five searches without reported truncation and
retrieved two detector-6 FITS cutouts and previews per field.

| Field | Returned images across six detectors | UTC observation date span |
| --- | --- | --- |
| Barnard's Star | 363 | 2025-08-15 to 2026-09-22 |
| Epsilon Indi B | 465 | 2025-04-24 to 2026-10-02 |
| WISE 0855 | 258 | 2025-05-05 to 2026-05-14 |
| RW Aurigae | 335 | 2025-09-01 to 2026-09-16 |
| R Draconis | 539 | 2025-05-16 to 2026-07-16 |

Some sample pixels have source-mask and artifact flags. One late Barnard's Star
preview has approximately 78% valid field coverage. The raw products and metadata
retain these conditions. The R Draconis samples have `OVERFLOW`, `SUR_ERROR`,
`SOURCE`, and `BLOOM` at the field center. Both RW Aurigae samples have `OVERFLOW`
and `SOURCE` there. One Epsilon Indi B sample also has `HALO`. These findings affect
subsequent photometric analysis even though the download and rendering checks passed.

Use the archive's DR1 spectral-image DOI `10.26131/IRSA678` when publishing results
from these data. The archive provides the requested mission acknowledgement and
the additional DOI for the all-sky cube. [Attribution guidance](https://irsa.ipac.caltech.edu/data/SPHEREx/docs/overview_dr1.html)
