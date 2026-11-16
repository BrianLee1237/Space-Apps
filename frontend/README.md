# SKYFRAME frontend

React + TypeScript + Vite + Tailwind. A public sky-region explorer for the NASA Space Apps 2026 SPHEREx challenge.

## Start the project

From the repository root, use the existing one-command launcher:

```bash
bash start.sh
```

The frontend runs at http://127.0.0.1:5173, and FastAPI on port 8000. You can run the frontend independently with `cd frontend && npm ci && npm run dev`.

## 3D celestial coordinate picker

- The **Navigator** mode shows a geometric WebGL sky-coordinate sphere, not a SPHEREx observation.
- **Drag** the globe to rotate; **scroll** (or use the +/- buttons) to zoom.
- **Click** the visible surface of the globe to select its actual Right Ascension and Declination; they appear in the sidebar RA/Dec fields.
- Press **Load SPHEREx data** in the globe or **Search** in the sidebar. The existing FastAPI observations API receives the selected coordinates and chosen field of view. The viewer switches to real **Observations** once a search starts.
- You may also type coordinates manually, including sexagesimal RA/Dec. The celestial sphere supports arrow-key rotation and Enter/Space to select the point at the center; the form works without WebGL.
- To return to the globe at any time, choose **Navigator** in the canvas header. The navbar's Explorer, Discover, Spectrum, Compare, Notebook and Guide tabs remain available.

## Data integrity

The globe contains only a mathematical J2000 coordinate grid. It does not generate stars, positions of detected objects, SPHEREx imagery, dates, spectra, or candidates. All science panels depend on real backend results. Missing backend features show the actual `No data` or error state.

## Architecture

- `src/components/CelestialNavigator.tsx`: standalone, dependency-free WebGL sphere and surface-to-coordinate conversion.
- `src/pages/Explorer.tsx`: controls navigator mode and delegates searching to the existing `loadObservations` flow.
- `src/celestial-theme.css`: mission-control visual identity, loaded after the main app CSS.
- `src/observatory.css`: responsive charcoal-and-gold finishing layer, loaded after the team theme.
- `src/services/api.ts`: FastAPI client, including on-demand frame metadata.

No additional npm dependencies are needed for the navigator.

## Time and change controls

The default sequence selects observations at least 30 days apart. The toolbar also
supports every exposure, one-day, and 180-day spacing. The timeline shows the real
date and elapsed days. Playback speed controls the on-screen frame duration.

**Highlight changes** compares the pair selected in Compare, initially the first
and last displayed epochs. Numbered rings, residual captions, and possible-motion
arrows appear over the comparison's later observation. Selecting a marker opens
its explanation and a real six-detector spectral request. Candidate annotations
are hidden on other epochs and combined images.

The UI combines displayed epochs through Brian's coadd endpoint. Spectrum samples
show error bars and individual observation dates on hover. Metadata includes
wavelength, bandwidth, PSF FWHM, and decoded quality flags when available.
