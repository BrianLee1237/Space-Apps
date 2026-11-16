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
  catalogMatches?: Array<CatalogSource & { separationArcsec: number }>
  supportingPairs?: number
  evidence?: Array<
    MatchedPair & {
      associationRadiusArcsec: number
      detectionThresholdSigma: number
    }
  >
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
export type OverlayResponse = {
  sources: CatalogSource[]
  catalog?: string
  warnings?: string[]
}
export type SavedFinding = {
  id: string
  savedAt: string
  note: string
  target: SearchTarget
  candidate?: Candidate
  selectedObservationId?: string
  observations: Array<
    Pick<Observation, 'id' | 'observedAt' | 'release' | 'flags'> &
      Partial<
        Pick<Observation, 'imageUrl' | 'detector' | 'centralWavelengthMicron'>
      >
  >
  motionSummary?: MotionTrack['summary']
  analysisWarnings?: string[]
  analysis?: ScienceResult
  settings?: {
    epochDays: number
    band: BandSelection
    fromId?: string
    toId?: string
  }
}

export type MatchedPair = {
  fromId: string
  toId: string
  earlierAt: string
  laterAt: string
  elapsedDays: number
  detector: number
  wavelengthMicron: number
  wavelengthDifferencePercent: number
  hasQualityFlags: boolean
}
export type MatchResponse = {
  pairs: MatchedPair[]
  inspected: number
  warnings: string[]
  method: string
}
export type MotionPoint = {
  observationId: string
  observedAt: string
  xFraction: number
  yFraction: number
  raDeg: number
  decDeg: number
  peakSnr: number
  wavelengthMicron: number
  uncertaintyArcsec?: number
}
export type MotionTrack = {
  fit?: MotionFit | null
  measurements: MotionPoint[]
  summary: {
    baselineDays: number
    apparentShiftArcsec: number
    apparentRateArcsecPerYear: number | null
    observationsMeasured: number
  } | null
  warnings: string[]
  method: string
}

export type ViewName =
  | 'shift-stack'
  | 'explorer'
  | 'science'
  | 'motion'
  | 'discover'
  | 'spectrum'
  | 'compare'
  | 'notebook'
  | 'guide'

export type ScienceSource = {
  referenceId: string
  x: number
  y: number
  ra?: number
  dec?: number
}
export type ScienceParameters = {
  kind:
    | 'matches'
    | 'photometry'
    | 'spectrum'
    | 'track'
    | 'stack'
    | 'shift-stack'
    | 'difference'
    | 'discover'
    | 'catalog'
  ids: string[]
  referenceId?: string
  x?: number
  y?: number
  ra?: number
  dec?: number
  radiusArcsec?: number
  epochDays?: number
  background?: 'none' | 'constant' | 'plane'
  eastRate?: number
  northRate?: number
  pixels?: number
  crossmatch?: boolean
}
export type PhotometricPoint = {
  observationId: string
  observedAt: string
  flux: number
  uncertainty: number
  wavelengthMicron: number
  channel: number | null
  detector: number
  coverageFraction: number
  qualityFlags: string[]
  apertureRadiusArcsec: number
}
export type MotionFit = {
  eastArcsecPerYear: number
  northArcsecPerYear: number
  rateUncertaintyArcsecPerYear: number
  referenceMjd: number
  reducedChiSquare: number | null
  assumedAstrometricFloorArcsec: number
}
export type Provenance = {
  algorithmVersion: string
  codeSha256: string
  calibrationSha256: string
  parameters: ScienceParameters
  observations: {
    id: string
    observedAt: string
    sha256: string
    release: string
    processingVersion: string
  }[]
}
export type ScienceResult = {
  samples?: PhotometricPoint[]
  channels?: {
    channel: number
    count: number
    meanFlux: number
    reducedChiSquare: number | null
  }[]
  cells?: {
    epoch: number
    channel: number
    flux: number
    uncertainty: number
    count: number
    startMjd: number
  }[]
  fit?: MotionFit | null
  measurements?: MotionPoint[]
  summary?: MotionTrack['summary']
  counterparts?: Array<CatalogSource & { separationArcsec: number }>
  detectorCoverage?: number[]
  candidates?: Candidate[]
  notes?: string
  pairs?: MatchedPair[]
  inspected?: number
  imageUrl?: string
  significanceUrl?: string
  staticImageUrl?: string
  channel?: number
  inputCount?: number
  rejectedPixels?: number
  empiricalPsfMatched?: boolean
  fluxUnit?: string
  position: { raDeg: number; decDeg: number }
  method: string
  warnings: string[]
  provenance: Provenance
}
export type AnalysisJob = {
  id: string
  subscription?: string
  state: 'queued' | 'running' | 'complete' | 'failed' | 'cancelled'
  completed: number
  total: number
  message: string
  result: ScienceResult | null
  error: string | null
}
export type EvidenceEntry = {
  id: string
  createdAt: string
  record: { target?: SearchTarget; note?: string; analysis?: ScienceResult }
  assessments: Partial<
    Record<
      'possible-motion' | 'possible-variability' | 'artifact' | 'uncertain',
      number
    >
  >
}
