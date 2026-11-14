# Backend handoff: SPHEREx Explorer

Frontend is React+TS+Tailwind v4, with NO bundled fabricated images, dates, flux, candidates, sources, or derived science. The UI requests real data from the API only when the user searches or selects a tool. It handles missing services with actual error states.

## Data sources and purpose

Use NASA/IPAC SPHEREx DR1 and QR3 spectral images for time-resolved imagery, and DR1's all-sky spectral cube for spectral access where appropriate. The official SPHEREx archive and science tools offer image cutouts, spectrophotometry and source discovery. Gaia DR3 is an optional catalog overlay. WISE/NEOSSat are references, not automatically supported overlay datasets.

- IRSA: https://irsa.ipac.caltech.edu/Missions/spherex.html
- DR1/QR3 guide: https://irsa.ipac.caltech.edu/spherex-archive-documentation/spherex-data-releases/
- IRSA tutorials: https://caltech-ipac.github.io/irsa-tutorials/spherex/
- CSA NEOSSat tutorial: https://github.com/asc-csa/NEOSSAT_Tutorial

## Frontend -> proposed FastAPI API

These are *proposed*, not live NASA endpoints. Implement these in backend; keep the response shape or coordinate contract changes with frontend teammate.

1. `GET /api/resolve?name=Barnard%27s%20Star` -> `{ "raDeg": 0, "decDeg": 0 }` **This object is ONLY a shape illustration, not target coordinates.** Resolver needs authoritative epoch handling and proper motion for fast-moving sources.
2. `GET /api/observations?ra=<degrees>&dec=<degrees>&fov=<arcmin>&mode=auto|detector|channel&index=<1-6|1-102>` -> `{ "target": {"raDeg": ..., "decDeg": ..., "fovArcmin": ...}, "observations": [ {"id":"<archive-id>","observedAt":"<UTC ISO-8601>","imageUrl":"<image-url>","release":"DR1|QR3","detector":1,"flags":["..."]} ] }`. Return [] when no data. Sort by acquisition time. Provide image URLs for server-rendered real cutout, not raw FITS browsers cannot render.
3. `GET /api/candidates?ra=<deg>&dec=<deg>&fov=<arcmin>&ids=<comma separated observation ids>` -> `{ "candidates": [ {"id":"<id>","raDeg":...,"decDeg":...,"xFraction":...,"yFraction":...,"notes":"..."} ], "method":"...","warnings":[] }`. Requires >=2 observations aligned and compared by science processor. NASA source discovery finds sources; **tracking their change across epochs requires additional work**. Candidates are not confirmed discoveries; include flags/uncertainty.
4. `GET /api/spectrum?observationId=<id>&x=<fraction>&y=<fraction>` or `GET /api/spectrum?ra=<deg>&dec=<deg>` -> `{ "samples":[ {"wavelengthMicron": ..., "flux": ..., "uncertainty": ...} ], "fluxUnit":"<real unit>", "extractionMethod":"<method>", "warnings":[] }`. Do not simply plot 102 arbitrary intensity values as a scientifically measured point-source spectrum. Extract/calibrate valid fluxes; include flags and warnings. Fractional image coordinates correspond to image pixels in the rendered cutout, with no padding offset.
5. `GET /api/difference?fromId=<id>&toId=<id>` -> `{ "imageUrl":"<aligned difference PNG>", "method":"<processing method>", "warnings":[] }`. Server must first resample to a common astrometric grid and apply proper brightness/noise treatment. Never return an unaligned subtraction as evidence.
6. `GET /api/overlays?observationId=<id>&catalog=gaia-dr3` -> `{ "sources": [{"id":"<catalog ID>","xFraction":0.5,"yFraction":0.5,"raDeg":...,"decDeg":...}] }`. Fractions must map accurately to the rendered cutout, taking sky WCS into account. Catalog coordinates need proper-motion propagation when applicable.

**Error contract:** HTTP 404 or 501 for not implemented, 4xx and 5xx JSON `{ "detail":"Human-readable error" }`. Avoid returning fake data to fill missing states. When data release changes, archive source should version files and metadata; prefer DR1+QR3 and do not silently mix QR2 calibrations.

## Frontend ownership

All UI files are under `frontend/src/`. Only `src/services/api.ts` contains HTTP operations, and `src/types/astronomy.ts` defines the boundary. Main app orchestration: `src/pages/Explorer.tsx`. Other components are visual UI. `src/components/Notebook.tsx` only exports the current user's notes with real observation IDs and dates; localStorage stores these locally until cleared. No server publication.

## No logo

The header says "SPHEREx Explorer" as plain text. No generated brand mark or NASA logo, and no API connection badge.
