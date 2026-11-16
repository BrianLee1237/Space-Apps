import { useEffect, useMemo, useRef, useState } from 'react'
import { AlertTriangle } from 'lucide-react'
import Navbar from '../components/Navbar'
import Sidebar from '../components/Sidebar'
import { parseSkyCoordinates } from '../services/coordinates'
import CelestialNavigator from '../components/CelestialNavigator'
import SkyViewer from '../components/SkyViewer'
import BeforeAfterSlider from '../components/BeforeAfterSlider'
import Timeline from '../components/Timeline'
import ScienceWorkspace from '../components/ScienceWorkspace'
import { runAnalysis } from '../services/science'
import Inspector from '../components/Inspector'
import {
  imageURL,
  getObservationMetadata,
  getGaiaOverlay,
  getObservations,
  getSpectrum,
  resolveTarget,
} from '../services/api'
import type {
  BandSelection,
  Candidate,
  CombineResponse,
  DifferenceResponse,
  DiscoveryResponse,
  ImageLocation,
  Observation,
  OverlayResponse,
  SavedFinding,
  SearchTarget,
  SpectrumRequest,
  SpectrumResponse,
  ViewName,
  MatchResponse,
  MotionTrack,
  ScienceSource,
  ScienceParameters,
  ScienceResult,
  AnalysisJob,
} from '../types/astronomy'

type LoadStatus = 'idle' | 'loading' | 'ready' | 'empty' | 'error'
type Selection =
  | { type: 'image'; point: ImageLocation }
  | { type: 'candidate'; candidate: Candidate }
  | null
const WISE0855: SearchTarget = {
  name: 'WISE 0855',
  raDeg: (8 + 55 / 60 + 10.831 / 3600) * 15,
  decDeg: -(7 + 14 / 60 + 42.53 / 3600),
  fovArcmin: 10,
}
const NOTES_KEY = 'spherex-explorer-notes-v1'
function readNotes(): SavedFinding[] {
  try {
    const value = JSON.parse(localStorage.getItem(NOTES_KEY) || '[]') as unknown
    return Array.isArray(value)
      ? value.filter(
          (v) => v && typeof v === 'object' && typeof v.id === 'string',
        )
      : []
  } catch {
    return []
  }
}
export default function Explorer() {
  const [viewerMode, setViewerMode] = useState<'globe' | 'observations'>(
    'globe',
  )
  const [view, setView] = useState<ViewName>(() => {
    const value = new URLSearchParams(location.search).get('view')
    return value &&
      [
        'explorer',
        'science',
        'motion',
        'discover',
        'spectrum',
        'compare',
        'notebook',
        'guide',
      ].includes(value)
      ? (value as ViewName)
      : 'explorer'
  })
  const [settingsOpen, setSettingsOpen] = useState(true)
  const [ra, setRa] = useState(''),
    [dec, setDec] = useState(''),
    [fov, setFov] = useState(10)
  const [band, setBand] = useState<BandSelection>({ mode: 'auto' })
  const [target, setTarget] = useState<SearchTarget | null>(null)
  const [status, setStatus] = useState<LoadStatus>('idle'),
    [loadError, setLoadError] = useState('')
  const [allFrames, setFrames] = useState<Observation[]>([]),
    [index, setIndex] = useState(0)
  const [epochDays, setEpochDays] = useState(() => {
    const value = Number(
      new URLSearchParams(location.search).get('epoch') ?? 30,
    )
    return [0, 1, 30, 180].includes(value) ? value : 30
  })
  const restored = useRef(new URLSearchParams(location.search))
  const frames = allFrames
  const playbackFrames = useMemo(() => {
    if (!epochDays) return allFrames
    const selected: Observation[] = []
    for (const observation of allFrames)
      if (
        !selected.length ||
        Date.parse(observation.observedAt) -
          Date.parse(selected[selected.length - 1].observedAt) >=
          epochDays * 86400000
      )
        selected.push(observation)
    return selected
  }, [allFrames, epochDays])
  const [scienceSource, setScienceSource] = useState<ScienceSource | null>(null)
  const [latestAnalysis, setLatestAnalysis] = useState<ScienceResult | null>(
    null,
  )
  const [mainJob, setMainJob] = useState<AnalysisJob | null>(null)
  const mainJobAbort = useRef<AbortController | null>(null),
    mainJobKind = useRef('')
  const [searchWarnings, setSearchWarnings] = useState<string[]>([])
  const [playing, setPlaying] = useState(false),
    [speed, setSpeed] = useState(700)
  const [brightness, setBrightness] = useState(100),
    [contrast, setContrast] = useState(100),
    [inverted, setInverted] = useState(false)
  const [gaiaEnabled, setGaiaEnabled] = useState(false),
    [gaiaResult, setGaiaResult] = useState<{
      id: string
      data: OverlayResponse
    } | null>(null)
  const [selection, setSelection] = useState<Selection>(null)
  const [spectrum, setSpectrum] = useState<SpectrumResponse | null>(null),
    [spectrumBusy, setSpectrumBusy] = useState(false),
    [spectrumError, setSpectrumError] = useState('')
  const [discovery, setDiscovery] = useState<DiscoveryResponse | null>(null),
    [discoveryBusy, setDiscoveryBusy] = useState(false),
    [discoveryError, setDiscoveryError] = useState('')
  const [diff, setDiff] = useState<DifferenceResponse | null>(null),
    [diffBusy, setDiffBusy] = useState(false),
    [diffError, setDiffError] = useState('')
  const [combine, setCombine] = useState<CombineResponse | null>(null),
    [combineBusy, setCombineBusy] = useState(false),
    [combineError, setCombineError] = useState('')
  const [from, setFrom] = useState(0),
    [to, setTo] = useState(1)
  const [guideBusy, setGuideBusy] = useState(false)
  const [activeGuide, setActiveGuide] = useState<string | null>(null)
  const [matches, setMatches] = useState<MatchResponse | null>(null),
    [matchBusy, setMatchBusy] = useState(false),
    [matchError, setMatchError] = useState('')
  const [track, setTrack] = useState<MotionTrack | null>(null),
    [trackBusy, setTrackBusy] = useState(false),
    [trackError, setTrackError] = useState('')
  const [sliderActive, setSliderActive] = useState(false)
  const [notes, setNotes] = useState<SavedFinding[]>(readNotes)
  const abort = useRef<AbortController | null>(null),
    seq = useRef(0),
    specSeq = useRef(0),
    discoverySeq = useRef(0),
    diffSeq = useRef(0),
    combineSeq = useRef(0),
    matchSeq = useRef(0),
    trackSeq = useRef(0)
  const spectrumAbort = useRef<AbortController | null>(null)
  const spectrumTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [frameDetails, setFrameDetails] = useState<Partial<Observation>>({})
  useEffect(
    () => () => {
      spectrumAbort.current?.abort()
      if (spectrumTimer.current !== null) clearTimeout(spectrumTimer.current)
    },
    [],
  )
  const rawFrame = frames[index] ?? null
  const frame = rawFrame
    ? { ...rawFrame, ...(frameDetails.id === rawFrame.id ? frameDetails : {}) }
    : null
  const frameId = rawFrame?.id
  const gaia =
    gaiaEnabled && gaiaResult?.id === frameId ? gaiaResult.data : null
  const timelineFrames =
    frame && !playbackFrames.some((observation) => observation.id === frame.id)
      ? [...playbackFrames, rawFrame!].sort(
          (a, b) => Date.parse(a.observedAt) - Date.parse(b.observedAt),
        )
      : playbackFrames
  const timelineIndex = timelineFrames.findIndex(
    (observation) => observation.id === frameId,
  )
  useEffect(() => {
    const params = new URLSearchParams(location.search)
    params.set('epoch', String(epochDays))
    params.set('view', view)
    if (frameId) params.set('obs', frameId.split('.')[1])
    if (scienceSource) {
      params.set('source', scienceSource.referenceId.split('.')[1])
      params.set('sx', String(scienceSource.x))
      params.set('sy', String(scienceSource.y))
      if (scienceSource.ra !== undefined && scienceSource.dec !== undefined) {
        params.set('sra', String(scienceSource.ra))
        params.set('sdec', String(scienceSource.dec))
      } else {
        params.delete('sra')
        params.delete('sdec')
      }
    }
    if (frames[from]) params.set('from', frames[from].id.split('.')[1])
    if (frames[to]) params.set('to', frames[to].id.split('.')[1])
    history.replaceState({}, '', location.pathname + '?' + params.toString())
  }, [epochDays, view, frameId, frames, from, to, scienceSource])

  const comparisonDates = [
    frames[from]?.observedAt,
    frames[to]?.observedAt,
  ].sort()
  const visibleCandidates = (discovery?.candidates ?? []).filter((candidate) =>
    diff
      ? candidate.earlierAt === comparisonDates[0] &&
        candidate.laterAt === comparisonDates[1]
      : candidate.laterAt === frame?.observedAt,
  )
  useEffect(() => {
    if (!frameId) return
    const ctrl = new AbortController()
    void getObservationMetadata(frameId, ctrl.signal)
      .then(setFrameDetails)
      .catch(() => {})
    return () => ctrl.abort()
  }, [frameId])
  useEffect(() => {
    if (!frames.length) return
    const next = frames[(index + 1) % frames.length]
    const preload = new Image()
    preload.src = imageURL(next.imageUrl)
  }, [frames, index])

  useEffect(() => {
    try {
      localStorage.setItem(NOTES_KEY, JSON.stringify(notes))
    } catch {
      /* Private-browsing storage can fail. */
    }
  }, [notes])
  useEffect(() => {
    if (!playing || playbackFrames.length < 2) return
    const handle = window.setInterval(
      () =>
        setIndex((current) => {
          const after =
            Date.parse(frames[current].observedAt) + epochDays * 86400000
          const next = frames.findIndex(
            (observation, i) =>
              i > current && Date.parse(observation.observedAt) >= after,
          )
          return next < 0 ? 0 : next
        }),
      speed,
    )
    return () => window.clearInterval(handle)
  }, [playing, frames, playbackFrames.length, epochDays, speed])
  useEffect(() => {
    if (!gaiaEnabled || !frameId) return
    const ctrl = new AbortController()
    void getGaiaOverlay(frameId, ctrl.signal)
      .then((data) => setGaiaResult({ id: frameId, data }))
      .catch((e) => {
        if (!ctrl.signal.aborted)
          setLoadError(
            e instanceof Error ? e.message : 'Unable to load Gaia overlay.',
          )
      })
    return () => ctrl.abort()
  }, [gaiaEnabled, frameId]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const rawRa = params.get('ra'),
      rawDec = params.get('dec'),
      rawFov = Number(params.get('fov') || 10)
    if (rawRa === null || rawDec === null) return
    // The backend accepts any continuous value in [0.5, 60] (models.py's
    // SearchRequest.fov_arcmin); snapping to the sidebar's five presets here
    // would silently ignore an embedded URL's requested field of view.
    const fovValue = Number.isFinite(rawFov)
      ? Math.min(60, Math.max(0.5, rawFov))
      : 10
    const position = parseSkyCoordinates(rawRa, rawDec, fovValue)
    if (!position) return
    const mode = params.get('mode'),
      value = Number(params.get('index'))
    const nextBand: BandSelection =
      mode === 'detector' && Number.isInteger(value) && value >= 1 && value <= 6
        ? { mode: 'detector', index: value }
        : mode === 'channel' &&
            Number.isInteger(value) &&
            value >= 1 &&
            value <= 102
          ? { mode: 'channel', index: value }
          : { mode: 'auto' }
    void loadObservations(position, nextBand)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(
    () => () => {
      abort.current?.abort()
      mainJobAbort.current?.abort()
    },
    [],
  )

  async function loadObservations(
    next: SearchTarget,
    nextBand: BandSelection = band,
    refresh = false,
  ) {
    abort.current?.abort()
    const ctrl = new AbortController()
    abort.current = ctrl
    const requestId = ++seq.current
    mainJobAbort.current?.abort()
    setMainJob(null)
    setScienceSource(null)
    setLatestAnalysis(null)
    setTarget(next)
    setFrames([])
    setIndex(0)
    setPlaying(false)
    setLoadError('')
    setStatus('loading')
    diffSeq.current++
    combineSeq.current++
    matchSeq.current++
    trackSeq.current++
    setDiffBusy(false)
    setCombineBusy(false)
    setMatchBusy(false)
    setTrackBusy(false)
    setMatches(null)
    setTrack(null)
    setSliderActive(false)
    setViewerMode('observations')
    specSeq.current++
    discoverySeq.current++
    setSpectrumBusy(false)
    setDiscoveryBusy(false)
    cancelSpectrum()
    setSpectrum(null)
    setSelection(null)
    setDiscovery(null)
    setDiff(null)
    setCombine(null)
    setGaiaResult(null)
    setGaiaEnabled(false)
    setDiscoveryError('')
    setSpectrumError('')
    setDiffError('')
    setCombineError('')
    setSearchWarnings([])
    setBand(nextBand)
    setMatchError('')
    setTrackError('')
    setRa(String(next.raDeg))
    setDec(String(next.decDeg))
    setFov(next.fovArcmin)
    const url = new URL(window.location.href)
    url.searchParams.set('ra', String(next.raDeg))
    url.searchParams.set('dec', String(next.decDeg))
    url.searchParams.set('fov', String(next.fovArcmin))
    url.searchParams.set('mode', nextBand.mode)
    if ('index' in nextBand)
      url.searchParams.set('index', String(nextBand.index))
    else url.searchParams.delete('index')
    window.history.replaceState({}, '', url.pathname + url.search + url.hash)
    try {
      const data = await getObservations(next, nextBand, ctrl.signal, refresh)
      if (ctrl.signal.aborted || seq.current !== requestId) return
      const findRestored = (key: string, fallback: number) => {
        const id = restored.current.get(key)
        const found = id
          ? data.observations.findIndex((frame) => frame.id.endsWith('.' + id))
          : -1
        return found >= 0 ? found : fallback
      }
      const restoredSource = data.observations.find((observation) =>
        observation.id.endsWith('.' + restored.current.get('source')),
      )
      const sx = Number(restored.current.get('sx')),
        sy = Number(restored.current.get('sy'))
      if (
        restoredSource &&
        Number.isFinite(sx) &&
        Number.isFinite(sy) &&
        sx >= 0 &&
        sx <= 1 &&
        sy >= 0 &&
        sy <= 1
      ) {
        const sra = Number(restored.current.get('sra')),
          sdec = Number(restored.current.get('sdec'))
        const skyPosition =
          restored.current.has('sra') &&
          restored.current.has('sdec') &&
          Number.isFinite(sra) &&
          Number.isFinite(sdec)
            ? { ra: sra, dec: sdec }
            : {}
        setScienceSource({
          referenceId: restoredSource.id,
          x: sx,
          y: sy,
          ...skyPosition,
        })
      }
      setIndex(findRestored('obs', 0))
      setFrom(findRestored('from', 0))
      setTo(findRestored('to', Math.max(0, data.observations.length - 1)))
      setPlaying(false)
      setFrames(data.observations)
      setStatus(data.observations.length ? 'ready' : 'empty')
      setSearchWarnings(data.warnings ?? [])
    } catch (e) {
      if (ctrl.signal.aborted || seq.current !== requestId) return
      setLoadError(
        e instanceof Error ? e.message : 'Unable to load observations.',
      )
      setStatus('error')
    }
  }
  function updateBand(next: BandSelection) {
    setBand(next)
    if (target) void loadObservations(target, next)
  }
  function updateFov(next: number) {
    setFov(next)
    if (target) void loadObservations({ ...target, fovArcmin: next })
  }
  function cancelSpectrum() {
    specSeq.current++
    spectrumAbort.current?.abort()
    if (spectrumTimer.current !== null) {
      clearTimeout(spectrumTimer.current)
      spectrumTimer.current = null
    }
    setSpectrumBusy(false)
  }
  function updateComparison(earlier: number, later: number) {
    diffSeq.current++
    combineSeq.current++
    discoverySeq.current++
    cancelSpectrum()
    setDiff(null)
    setCombine(null)
    setDiscovery(null)
    setSelection(null)
    setSpectrum(null)
    setSliderActive(false)
    setDiffBusy(false)
    setCombineBusy(false)
    setDiscoveryBusy(false)
    setFrom(earlier)
    setTo(later)
  }
  function updatePlaying(value: boolean) {
    if (value) {
      diffSeq.current++
      combineSeq.current++
      if (['difference', 'stack'].includes(mainJobKind.current))
        mainJobAbort.current?.abort()
      setDiff(null)
      setCombine(null)
      setDiffBusy(false)
      setCombineBusy(false)
      setSliderActive(false)
    }
    setPlaying(value)
  }
  function cancelTracking() {
    if (mainJobKind.current === 'track') mainJobAbort.current?.abort()
    trackSeq.current++
    setTrack(null)
    setTrackBusy(false)
    setTrackError('')
  }
  function changeIndex(i: number) {
    diffSeq.current++
    combineSeq.current++
    cancelSpectrum()
    cancelTracking()
    setDiffBusy(false)
    setCombineBusy(false)
    setIndex(i)
    setPlaying(false)
    setDiff(null)
    setCombine(null)
    setSliderActive(false)
    setSpectrum(null)
    setSelection(null)
  }
  function queueSpectrum(request: SpectrumRequest) {
    cancelSpectrum()
    const requestId = specSeq.current
    setSpectrum(null)
    setSpectrumError('')
    setSpectrumBusy(true)
    spectrumTimer.current = setTimeout(() => {
      spectrumTimer.current = null
      const controller = new AbortController()
      spectrumAbort.current = controller
      void getSpectrum(request, controller.signal)
        .then((result) => {
          if (specSeq.current === requestId && !controller.signal.aborted)
            setSpectrum(result)
        })
        .catch((error) => {
          if (specSeq.current !== requestId || controller.signal.aborted) return
          setSpectrumError(
            error instanceof Error ? error.message : 'No spectrum available.',
          )
        })
        .finally(() => {
          if (specSeq.current === requestId) {
            setSpectrumBusy(false)
            spectrumAbort.current = null
          }
        })
    }, 250)
  }
  function inspect(point: ImageLocation) {
    if (!frame) return
    cancelTracking()
    setLatestAnalysis(null)
    setScienceSource({
      referenceId: frame.id,
      x: point.xFraction,
      y: point.yFraction,
    })
    setSelection({ type: 'image', point })
    queueSpectrum({
      observationId: frame.id,
      xFraction: point.xFraction,
      yFraction: point.yFraction,
    })
  }
  function inspectCandidate(candidate: Candidate) {
    cancelTracking()
    setLatestAnalysis(null)
    diffSeq.current++
    combineSeq.current++
    setDiffBusy(false)
    setCombineBusy(false)
    const candidateIndex = frames.findIndex(
      (observation) => observation.observedAt === candidate.laterAt,
    )
    const observation = candidateIndex >= 0 ? frames[candidateIndex] : frame
    if (candidateIndex >= 0) setIndex(candidateIndex)
    setPlaying(false)
    setDiff(null)
    setCombine(null)
    setSliderActive(false)
    setViewerMode('observations')
    if (observation)
      setScienceSource({
        referenceId: observation.id,
        x: candidate.xFraction ?? 0.5,
        y: candidate.yFraction ?? 0.5,
        ra: candidate.raDeg,
        dec: candidate.decDeg,
      })
    setSelection({ type: 'candidate', candidate })
    setView('spectrum')
    queueSpectrum({
      observationId: observation?.id,
      raDeg: candidate.raDeg,
      decDeg: candidate.decDeg,
    })
  }
  async function analyse(parameters: ScienceParameters) {
    mainJobAbort.current?.abort()
    const controller = new AbortController()
    mainJobAbort.current = controller
    mainJobKind.current = parameters.kind
    try {
      const result = await runAnalysis(parameters, controller.signal, (job) => {
        if (mainJobAbort.current === controller) setMainJob(job)
      })
      if (!controller.signal.aborted) setLatestAnalysis(result)
      return result
    } finally {
      if (mainJobAbort.current === controller) setMainJob(null)
    }
  }
  const selectedMatchedPair =
    matches?.pairs.find(
      (pair) =>
        frames[from]?.id === pair.fromId && frames[to]?.id === pair.toId,
    ) ?? null
  async function findMatches() {
    if (frames.length < 2) return
    const id = ++matchSeq.current
    setMatchBusy(true)
    setMatchError('')
    setMatches(null)
    setSliderActive(false)
    try {
      const result = await analyse({
        kind: 'matches',
        ids: frames.map((f) => f.id),
        ...(scienceSource ?? { referenceId: frame?.id }),
      })
      if (matchSeq.current !== id) return
      setMatches({
        pairs: result.pairs ?? [],
        inspected: result.inspected ?? 0,
        warnings: result.warnings,
        method: result.method,
      })
      if (result.pairs?.length) {
        const pair = result.pairs[0]
        const earlier = frames.findIndex((f) => f.id === pair.fromId),
          later = frames.findIndex((f) => f.id === pair.toId)
        if (earlier >= 0 && later >= 0) {
          updateComparison(earlier, later)
          setViewerMode('observations')
          setPlaying(false)
        }
      }
    } catch (e) {
      if ((e as Error).name !== 'AbortError' && matchSeq.current === id)
        setMatchError(
          e instanceof Error ? e.message : 'Could not compare wavelengths.',
        )
    } finally {
      if (matchSeq.current === id) setMatchBusy(false)
    }
  }
  async function runTracking() {
    if (selection?.type !== 'image' || !frame || frames.length < 2) {
      setTrackError('Select a visible source in an observation first.')
      return
    }
    const id = ++trackSeq.current
    setTrack(null)
    setTrackError('')
    setTrackBusy(true)
    setPlaying(false)
    const source = selection.point,
      reference = frame.id
    try {
      const result = await analyse({
        kind: 'track',
        ids: frames.map((f) => f.id),
        referenceId: reference,
        x: source.xFraction,
        y: source.yFraction,
      })
      if (trackSeq.current !== id) return
      setTrack({
        measurements: result.measurements ?? [],
        summary: result.summary ?? null,
        fit: result.fit,
        warnings: result.warnings,
        method: result.method,
      })
      setViewerMode('observations')
      setView('motion')
    } catch (e) {
      if ((e as Error).name !== 'AbortError' && trackSeq.current === id)
        setTrackError(
          e instanceof Error ? e.message : 'Could not track this source.',
        )
    } finally {
      if (trackSeq.current === id) setTrackBusy(false)
    }
  }
  function toggleSlider() {
    if (!selectedMatchedPair) return
    setPlaying(false)
    setDiff(null)
    setCombine(null)
    setViewerMode('observations')
    setSliderActive((v) => !v)
  }
  async function scan() {
    if (!target || frames.length < 2) return
    const requestId = ++discoverySeq.current
    diffSeq.current++
    combineSeq.current++
    setDiffBusy(false)
    setCombineBusy(false)
    setDiff(null)
    setCombine(null)
    setDiscovery(null)
    setDiscoveryError('')
    setDiscoveryBusy(true)
    setSliderActive(false)
    setPlaying(false)
    try {
      const result = await analyse({
        kind: 'discover',
        ids: frames.map((f) => f.id),
        crossmatch: gaiaEnabled,
        ...(scienceSource ?? { referenceId: frame?.id }),
      })
      if (discoverySeq.current !== requestId) return
      setDiscovery({
        candidates: result.candidates ?? [],
        method: result.method,
        warnings: result.warnings,
        notes: result.notes,
      })
      const candidateIndex = frames.findIndex(
        (observation) =>
          observation.observedAt === result.candidates?.[0]?.laterAt,
      )
      if (candidateIndex >= 0) setIndex(candidateIndex)
      setViewerMode('observations')
    } catch (e) {
      if (
        (e as Error).name !== 'AbortError' &&
        discoverySeq.current === requestId
      )
        setDiscoveryError(
          e instanceof Error ? e.message : 'Candidate scan unavailable.',
        )
    } finally {
      if (discoverySeq.current === requestId) setDiscoveryBusy(false)
    }
  }
  async function compare() {
    if (frames.length < 2 || from === to) return
    const requestId = ++diffSeq.current
    combineSeq.current++
    setCombineBusy(false)
    setDiff(null)
    setCombine(null)
    setDiffError('')
    setDiffBusy(true)
    setPlaying(false)
    setSliderActive(false)
    try {
      const result = await analyse({
        kind: 'difference',
        ids: [frames[from].id, frames[to].id],
        referenceId: frames[from].id,
        x: scienceSource?.x ?? 0.5,
        y: scienceSource?.y ?? 0.5,
        background: 'plane',
      })
      if (diffSeq.current !== requestId) return
      setDiff({
        imageUrl: result.imageUrl!,
        method: result.method,
        warnings: result.warnings,
      })
      setViewerMode('observations')
    } catch (e) {
      if ((e as Error).name === 'AbortError' || diffSeq.current !== requestId)
        return
      setDiffError(
        e instanceof Error ? e.message : 'Unable to generate difference image.',
      )
    } finally {
      if (diffSeq.current === requestId) setDiffBusy(false)
    }
  }
  async function combineStack() {
    if (frames.length < 2) return
    const requestId = ++combineSeq.current
    diffSeq.current++
    setDiffBusy(false)
    setCombine(null)
    setDiff(null)
    setCombineError('')
    setCombineBusy(true)
    setPlaying(false)
    setSliderActive(false)
    try {
      const result = await analyse({
        kind: 'stack',
        ids: frames.map((f) => f.id),
        referenceId: frame?.id,
        x: scienceSource?.x ?? 0.5,
        y: scienceSource?.y ?? 0.5,
      })
      if (combineSeq.current !== requestId) return
      setCombine({
        imageUrl: result.imageUrl!,
        frameCount: result.inputCount ?? 0,
        method: result.method,
        warnings: result.warnings,
      })
      setViewerMode('observations')
    } catch (e) {
      if (
        (e as Error).name === 'AbortError' ||
        combineSeq.current !== requestId
      )
        return
      setCombineError(
        e instanceof Error ? e.message : 'Unable to combine exposures.',
      )
    } finally {
      if (combineSeq.current === requestId) setCombineBusy(false)
    }
  }
  async function guidedSearch(name: string) {
    setGuideBusy(true)
    setLoadError('')
    setActiveGuide(name)
    try {
      if (name === 'WISE 0855') {
        await loadObservations({ ...WISE0855, fovArcmin: fov })
        setView('guide')
        return
      }
      const result = await resolveTarget(name)
      await loadObservations({ ...result, name, fovArcmin: fov })
      setView('guide')
    } catch (e) {
      setView('guide')
      setFrames([])
      setIndex(0)
      setTarget(null)
      setLoadError(e instanceof Error ? e.message : 'Unable to resolve target.')
      setStatus('error')
    } finally {
      setGuideBusy(false)
    }
  }
  function saveNote(note: string) {
    if (!target || !frames.length) return
    const finding: SavedFinding = {
      id: crypto.randomUUID?.() ?? String(Date.now()),
      savedAt: new Date().toISOString(),
      note,
      target,
      candidate:
        selection?.type === 'candidate' ? selection.candidate : undefined,
      selectedObservationId: frame?.id,
      observations: frames.map((o) => ({
        id: o.id,
        observedAt: o.observedAt,
        release: o.release,
        flags: o.flags,
        imageUrl: o.imageUrl,
        detector: o.detector,
        centralWavelengthMicron: o.centralWavelengthMicron,
      })),
      motionSummary: track?.summary ?? undefined,
      analysisWarnings: track?.warnings,
      analysis: latestAnalysis ?? undefined,
      settings: {
        epochDays,
        band,
        fromId: frames[from]?.id,
        toId: frames[to]?.id,
      },
    }
    setNotes((old) => [finding, ...old])
  }
  return (
    <div className="app-shell">
      <Navbar
        view={view}
        onView={setView}
        settingsOpen={settingsOpen}
        onToggleSettings={() => setSettingsOpen((v) => !v)}
      />
      <div className="epoch-toolbar">
        <button
          type="button"
          className="search-open"
          onClick={() => setSettingsOpen(true)}
        >
          Coordinates
        </button>
        <label>
          Time spacing{' '}
          <select
            aria-label="Minimum epoch separation"
            value={epochDays}
            onChange={(e) => setEpochDays(Number(e.target.value))}
          >
            <option value={0}>All exposures</option>
            <option value={1}>At least 1 day</option>
            <option value={30}>At least 30 days</option>
            <option value={180}>At least 180 days</option>
          </select>
        </label>
        <button
          disabled={frames.length < 2 || discoveryBusy}
          onClick={() => {
            setView('discover')
            void scan()
          }}
        >
          {discoveryBusy ? 'Checking…' : 'Find changes'}
        </button>
        <button
          disabled={!target || status === 'loading'}
          onClick={() => {
            if (target) void loadObservations(target, band, true)
          }}
        >
          Refresh archive
        </button>
        <span className="toolbar-status" role="status">
          {status === 'loading'
            ? 'Loading observations…'
            : status === 'error'
              ? 'Search failed'
              : allFrames.length
                ? `${playbackFrames.length} playback epochs / ${allFrames.length} exposures`
                : 'No observations loaded'}
        </span>
      </div>
      {mainJob && (
        <div className="analysis-progress" role="status">
          <span>
            {mainJob.message} · {mainJob.completed}/{mainJob.total || '…'}
          </span>
          <button onClick={() => mainJobAbort.current?.abort()}>
            Cancel analysis
          </button>
        </div>
      )}
      <div
        className={`workspace ${settingsOpen ? 'workspace-with-settings' : 'workspace-no-settings'}`}
      >
        {settingsOpen && (
          <Sidebar
            ra={ra}
            dec={dec}
            onRa={setRa}
            onDec={setDec}
            fov={fov}
            onFov={updateFov}
            band={band}
            onBand={updateBand}
            gaia={gaiaEnabled}
            onGaia={setGaiaEnabled}
            hasFrames={!!frame}
            gaiaWarnings={gaia?.warnings}
            brightness={brightness}
            onBrightness={setBrightness}
            contrast={contrast}
            onContrast={setContrast}
            inverted={inverted}
            onInvert={setInverted}
            loading={status === 'loading'}
            error={status === 'error' ? loadError : ''}
            onSearch={(t) => {
              setView('explorer')
              if (window.innerWidth < 950) setSettingsOpen(false)
              void loadObservations(t)
            }}
            onClose={() => setSettingsOpen(false)}
          />
        )}
        <div className="viewer-workspace">
          <div className="viewer-mode-header">
            <div className="viewer-mode-title">
              <strong>
                {viewerMode === 'globe'
                  ? 'Celestial navigator'
                  : target?.name || 'SPHEREx observations'}
              </strong>
              <small>
                {viewerMode === 'globe'
                  ? 'Click the globe to select coordinates'
                  : 'SPHEREx image viewer'}
              </small>
            </div>
            <div
              className="viewer-mode-buttons"
              role="group"
              aria-label="Viewer mode"
            >
              <button
                aria-pressed={viewerMode === 'globe'}
                className={viewerMode === 'globe' ? 'mode-active' : ''}
                onClick={() => setViewerMode('globe')}
              >
                Navigator
              </button>
              <button
                aria-pressed={viewerMode === 'observations'}
                className={viewerMode === 'observations' ? 'mode-active' : ''}
                onClick={() => setViewerMode('observations')}
              >
                Observations
              </button>
            </div>
          </div>
          <div className="viewer-mode-content">
            {view === 'science' ? (
              <ScienceWorkspace
                target={target}
                frames={allFrames}
                source={scienceSource}
                onResult={setLatestAnalysis}
                onSelectSource={() => {
                  setView('explorer')
                  setViewerMode('observations')
                }}
                onNavigate={(position) => {
                  setView('explorer')
                  void loadObservations(position)
                }}
              />
            ) : viewerMode === 'globe' ? (
              <CelestialNavigator
                selectedRa={parseSkyCoordinates(ra, dec, fov)?.raDeg ?? null}
                selectedDec={parseSkyCoordinates(ra, dec, fov)?.decDeg ?? null}
                fovArcmin={fov}
                loading={status === 'loading'}
                onPick={(r, d) => {
                  setRa(r.toFixed(6))
                  setDec(d.toFixed(6))
                }}
                onSearch={() => {
                  const picked = parseSkyCoordinates(ra, dec, fov)
                  if (picked) void loadObservations(picked)
                }}
              />
            ) : sliderActive &&
              selectedMatchedPair &&
              frames[from] &&
              frames[to] ? (
              <BeforeAfterSlider
                key={frames[from].id + frames[to].id}
                earlier={frames[from]}
                later={frames[to]}
                onClose={() => setSliderActive(false)}
              />
            ) : (
              <SkyViewer
                frame={frame}
                track={track}
                differenceUrl={diff?.imageUrl}
                combineUrl={combine?.imageUrl}
                status={status}
                error={loadError}
                candidates={visibleCandidates}
                gaia={gaia}
                brightness={brightness}
                contrast={contrast}
                inverted={inverted}
                onInspect={(p) => void inspect(p)}
                onCandidate={(c) => void inspectCandidate(c)}
              />
            )}
            {loadError && status === 'ready' && (
              <div className="overlay-error" role="alert">
                <AlertTriangle size={15} />
                {loadError}
                <button
                  type="button"
                  onClick={() => setLoadError('')}
                  aria-label="Dismiss error"
                >
                  ×
                </button>
              </div>
            )}
          </div>
        </div>
        <Inspector
          view={view}
          frame={frame}
          frames={frames}
          selection={selection}
          spectrum={spectrum}
          spectrumBusy={spectrumBusy}
          spectrumError={spectrumError}
          discovery={discovery}
          discoveryBusy={discoveryBusy}
          discoveryError={discoveryError}
          track={track}
          trackBusy={trackBusy}
          trackError={trackError}
          onTrack={() => void runTracking()}
          onScan={() => void scan()}
          onCandidate={(c) => void inspectCandidate(c)}
          diff={diff}
          diffBusy={diffBusy}
          diffError={diffError}
          compareFrom={from}
          compareTo={to}
          onFrom={(value) => updateComparison(value, to)}
          onTo={(value) => updateComparison(from, value)}
          onGenerateDifference={() => void compare()}
          onClearDifference={() => setDiff(null)}
          matches={matches}
          matchBusy={matchBusy}
          matchError={matchError}
          onFindMatches={() => void findMatches()}
          matchedPair={selectedMatchedPair}
          sliderActive={sliderActive}
          onToggleSlider={toggleSlider}
          combine={combine}
          combineBusy={combineBusy}
          combineError={combineError}
          onGenerateCombine={() => void combineStack()}
          onClearCombine={() => setCombine(null)}
          target={target}
          notes={notes}
          onSaveNote={saveNote}
          onDeleteNote={(id) =>
            setNotes((v) => v.filter((item) => item.id !== id))
          }
          onGuideTarget={(name) => void guidedSearch(name)}
          guideBusy={guideBusy}
          activeGuide={activeGuide}
          onGoCompare={() => {
            setView('compare')
            void findMatches()
          }}
          onGoDiscover={() => setView('discover')}
          onGoMotion={() => setView('motion')}
          onGoNotebook={() => setView('notebook')}
          searchWarnings={searchWarnings}
        />
        <Timeline
          frames={timelineFrames}
          index={Math.max(0, timelineIndex)}
          onIndex={(i) =>
            changeIndex(
              frames.findIndex(
                (observation) => observation.id === timelineFrames[i].id,
              ),
            )
          }
          playing={playing}
          onPlaying={updatePlaying}
          speed={speed}
          onSpeed={setSpeed}
        />
      </div>
    </div>
  )
}
