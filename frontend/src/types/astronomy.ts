/** Proposed frontend/backend contract. No mock images, stars, discoveries, or spectra. */
export type BandSelection =
  | { mode: 'auto' }
  | { mode: 'detector'; index: number }
  | { mode: 'channel'; index: number }

export type SearchTarget = {
  raDeg: number
  decDeg: number
  fovArcmin: number
  name?: string
}

export type Observation = {
  id: string
  observedAt: string // UTC ISO date, from the archive
  imageUrl: string // Backend-rendered real data; PNG/WebP/JPEG, no invented URLs
  release?: string // DR1, QR3, etc.
  detector?: number
  channel?: number
  centralWavelengthMicron?: number
  bandwidthMicron?: number
  psfFwhmArcsec?: number
  flags?: string[] // Only real decoded contamination or quality flags
  exposureSeconds?: number
  width?: number
  height?: number
  imageAligned?: boolean // True only when backend has aligned all returned observations
}
export type ObservationsResponse = {
  target: SearchTarget
  observations: Observation[]
  dataUpdatedAt?: string
  dataRelease?: string
  warnings?: string[]
}
export type ResolvedTarget = { raDeg: number; decDeg: number; name?: string }
export type ImageLocation = { xFraction: number; yFraction: number }
export type Candidate = {
  id: string
  label?: string
  raDeg: number
  decDeg: number
  xFraction?: number
  yFraction?: number
  classification?: string
  caption?: string
  previousXFraction?: number
  previousYFraction?: number
  elapsedDays?: number
  earlierAt?: string
  laterAt?: string
  displacementArcsec?: number
  brightnessChange?: number
  method?: string
  qualityFlags?: string[]
  notes?: string
}
export type DiscoveryResponse = {
  candidates: Candidate[]
  method?: string
  notes?: string
  warnings?: string[]
}
export type SpectrumRequest = {
  observationId?: string
  xFraction?: number
  yFraction?: number
  raDeg?: number
  decDeg?: number
}
export type SpectrumSample = {
  wavelengthMicron: number
  flux: number
  uncertainty?: number
  qualityFlags?: string[]
  observedAt?: string
}
export type SpectrumResponse = {
  samples: SpectrumSample[]
  fluxUnit: string
  extractionMethod?: string
  sourceLabel?: string
  warnings?: string[]
}
export type DifferenceResponse = {
  imageUrl: string
  method?: string
  warnings?: string[]
}
export type CombineResponse = {
  imageUrl: string
  frameCount: number
  method?: string
  warnings?: string[]
}
export type CatalogSource = {
  id: string
  label?: string
  xFraction: number
  yFraction: number
  raDeg?: number
  decDeg?: number
}
export type OverlayResponse = { sources: CatalogSource[]; catalog?: string; warnings?: string[] }
export type SavedFinding = {
  id: string
  savedAt: string
  note: string
  target: SearchTarget
  candidate?: Candidate
  selectedObservationId?: string
  observations: Array<Pick<Observation,'id'|'observedAt'|'release'|'flags'>>
}
export type ViewName = 'explorer' | 'discover' | 'spectrum' | 'compare' | 'notebook' | 'guide'
