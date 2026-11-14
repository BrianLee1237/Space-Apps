# SPHEREx Explorer frontend design

- **Product:** A public viewer for time-series SPHEREx sky imagery, built for the 2026 NASA Space Apps challenge.
- **Visual direction:** Dark scientific workbench combining NASA Eyes' immersive canvas with NASA Worldview's practical time and layer controls.
- **Primary task:** Search by RA/Dec -> inspect genuinely returned observations -> blink epochs -> flag potential changes.
- **Navigation:** Explorer / Discover / Spectrum / Compare / Notebook / Guide, with a visible Settings control and sidebar.
- **Spatial structure:** 294px left settings, flexible central image viewer, 326px right inspector; full-width observation timeline below viewer/inspector.
- **Palette:** Quiet navy background #080e16, charcoal panels #0f1823, 1px lines #273341, pale text and single functional blue #3f96fa.
- **Typography:** Native system sans. Compact functional labels; no marketing slogans or all-caps decorative statements.
- **Empty states:** Literally `No data`, `No observations`, `No spectrum available`, `No saved notes`, with truthful recovery instructions.
- **Assets:** No generated logo, fake sky photographs, simulated image epochs, or invented scientific measurements.
- **Responsive:** Controls become a dismissible drawer at laptop/tablet sizes, and a stack under 690px.
- **Scientific correctness:** Show observations/flags only as returned; candidate detections always remain unverified; spectra have measured values, unit, method and warnings only if provided.
- **Backend:** Single `src/services/api.ts` module with a documented proposed FastAPI contract. Frontend stores notebook notes only in browser storage.
