import { useEffect, useRef, useState } from 'react'
import { imageURL } from '../services/api'
import {
  assessEvidence,
  listEvidence,
  getEvidence,
  runAnalysis,
  saveEvidence,
} from '../services/science'
import type {
  AnalysisJob,
  EvidenceEntry,
  PhotometricPoint,
  ScienceParameters,
  ScienceResult,
  ScienceSource,
  SearchTarget,
  Observation,
} from '../types/astronomy'
import SkyAtlas from './SkyAtlas'
import SpectrumPlot from './SpectrumPlot'

type Props = {
  target: SearchTarget | null
  frames: Observation[]
  source: ScienceSource | null
  onResult: (result: ScienceResult) => void
  onSelectSource: () => void
  onNavigate: (target: SearchTarget) => void
}
type Tab = 'photometry' | 'images' | 'atlas' | 'review'
function download(value: string, name: string, type: string) {
  const url = URL.createObjectURL(new Blob([value], { type })),
    link = document.createElement('a')
  link.href = url
  link.download = name
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 2000)
}
function pointCsv(points: PhotometricPoint[]) {
  const columns = [
    'observationId',
    'observedAt',
    'wavelengthMicron',
    'channel',
    'flux',
    'uncertainty',
    'coverageFraction',
    'apertureRadiusArcsec',
  ] as const
  const quote = (value: unknown) =>
    `"${String(value ?? '').replace(/"/g, '""')}"`
  return [
    columns.join(','),
    ...points.map((point) =>
      columns.map((column) => quote(point[column])).join(','),
    ),
  ].join('\n')
}

function LightCurve({
  points,
  channel,
}: {
  points: PhotometricPoint[]
  channel: number
}) {
  const selected = points.filter((point) => point.channel === channel)
  if (!selected.length) return <p>No measurements in this channel.</p>
  const times = selected.map((point) => Date.parse(point.observedAt)),
    first = Math.min(...times),
    last = Math.max(...times)
  const low = Math.min(
      ...selected.map((point) => point.flux - point.uncertainty),
    ),
    high = Math.max(...selected.map((point) => point.flux + point.uncertainty))
  const x = (time: number) =>
    58 + ((time - first) / Math.max(86400000, last - first)) * 610
  const y = (flux: number) =>
    220 - ((flux - low) / Math.max(1e-12, high - low)) * 180
  return (
    <div
      className="science-chart"
      role="img"
      aria-label={`Aperture light curve with ${selected.length} observations in channel ${channel}`}
    >
      <svg viewBox="0 0 710 270">
        {[0, 0.5, 1].map((fraction) => (
          <g key={fraction}>
            <line
              x1="58"
              x2="680"
              y1={220 - fraction * 180}
              y2={220 - fraction * 180}
              stroke="#343c46"
            />
            <text x="50" y={224 - fraction * 180} textAnchor="end">
              {(low + fraction * (high - low)).toPrecision(3)}
            </text>
          </g>
        ))}
        <text x="58" y="22">
          Aperture flux · mJy
        </text>
        {selected.map((point, i) => (
          <g key={point.observationId}>
            <title>{`${point.observedAt} · ${point.flux.toPrecision(4)} ± ${point.uncertainty.toPrecision(3)} mJy · ${point.wavelengthMicron.toFixed(4)} µm`}</title>
            <line
              x1={x(times[i])}
              x2={x(times[i])}
              y1={y(point.flux - point.uncertainty)}
              y2={y(point.flux + point.uncertainty)}
              stroke="#d6ad74"
            />
            <circle cx={x(times[i])} cy={y(point.flux)} r="4" fill="#ecc58d" />
          </g>
        ))}
        <text x="58" y="248">
          {new Date(first).toLocaleDateString(undefined, { timeZone: 'UTC' })}
        </text>
        <text x="680" y="248" textAnchor="end">
          {new Date(last).toLocaleDateString(undefined, { timeZone: 'UTC' })}
        </text>
        <text x="365" y="265" textAnchor="middle">Observation date (UTC)</text>
      </svg>
    </div>
  )
}

function WavelengthTime({
  result,
  onChannel,
}: {
  result: ScienceResult
  onChannel: (channel: number) => void
}) {
  const cells = result.cells ?? [],
    epochs = [...new Set(cells.map((cell) => cell.epoch))].sort((a, b) => a - b)
  const channels = [...new Set(cells.map((cell) => cell.channel))].sort(
    (a, b) => a - b,
  )
  if (!cells.length) return <p>No valid wavelength/time cells are available.</p>
  return (
    <div className="wavelength-time">
      <div className="section-heading-row">
        <h3>Wavelength × time</h3>
        <span>{result.provenance.parameters.epochDays ?? 30}-day cells</span>
      </div>
      <p className="control-hint">
        Select a cell to inspect its channel. Amber is brighter and blue is
        dimmer than that channel’s mean. Empty cells have no measurements.
      </p>
      <div className="heatmap-scroll">
        <div
          className="heatmap"
          style={{
            gridTemplateColumns: `65px repeat(${epochs.length},minmax(42px,1fr))`,
          }}
        >
          <span>Channel</span>
          {epochs.map((epoch) => (
            <span key={epoch}>
              +{epoch * (result.provenance.parameters.epochDays ?? 30)}d
            </span>
          ))}
          {channels.map((channel) => {
            const mean =
              result.channels?.find((row) => row.channel === channel)
                ?.meanFlux ?? 0
            return (
              <div className="heatmap-row" key={channel}>
                <span>{channel}</span>
                {epochs.map((epoch) => {
                  const cell = cells.find(
                    (value) =>
                      value.epoch === epoch && value.channel === channel,
                  )
                  const change = cell
                    ? (cell.flux - mean) /
                      Math.max(Math.abs(mean), cell.uncertainty)
                    : 0
                  const intensity = Math.min(0.85, 0.12 + Math.abs(change))
                  return (
                    <button
                      key={epoch}
                      disabled={!cell}
                      onClick={() => onChannel(channel)}
                      style={{
                        background: cell
                          ? change >= 0
                            ? `rgba(223,174,101,${intensity})`
                            : `rgba(85,163,200,${intensity})`
                          : '#111720',
                      }}
                      title={
                        cell
                          ? `${cell.count} observations · ${cell.flux.toPrecision(4)} ± ${cell.uncertainty.toPrecision(3)} mJy`
                          : 'No measurement'
                      }
                      aria-label={`Channel ${channel}, epoch ${epoch}, ${cell ? cell.count + ' measurements' : 'no coverage'}`}
                    >
                      {cell ? cell.count : '·'}
                    </button>
                  )
                })}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

export default function ScienceWorkspace({
  target,
  frames,
  source,
  onResult,
  onSelectSource,
  onNavigate,
}: Props) {
  const [tab, setTab] = useState<Tab>('photometry'),
    [radius, setRadius] = useState(12),
    [days, setDays] = useState(30)
  const [background, setBackground] = useState<'none' | 'constant' | 'plane'>(
    'constant',
  )
  const [east, setEast] = useState(0),
    [north, setNorth] = useState(0)
  const [catalog, setCatalog] = useState<ScienceResult | null>(null)
  const [channel, setChannel] = useState<number | null>(null)
  const [photometry, setPhotometry] = useState<ScienceResult | null>(null),
    [image, setImage] = useState<ScienceResult | null>(null),
    [track, setTrack] = useState<ScienceResult | null>(null)
  const [last, setLast] = useState<ScienceResult | null>(null),
    [job, setJob] = useState<AnalysisJob | null>(null),
    [busy, setBusy] = useState(false)
  const [error, setError] = useState(''),
    [note, setNote] = useState(''),
    [message, setMessage] = useState('')
  const [entries, setEntries] = useState<EvidenceEntry[]>([]),
    [reviewNote, setReviewNote] = useState('')
  const controller = useRef<AbortController | null>(null),
    generation = useRef(0)
  const [reviewer] = useState(() => {
    const key = 'spherex-reviewer'
    try {
      let value = localStorage.getItem(key)
      if (!value) {
        value = crypto.randomUUID()
        localStorage.setItem(key, value)
      }
      return value
    } catch {
      return crypto.randomUUID()
    }
  })
  useEffect(() => () => controller.current?.abort(), [])
  useEffect(() => {
    if (tab === 'review')
      void listEvidence()
        .then((data) => setEntries(data.entries))
        .catch((reason) => setError(String(reason)))
  }, [tab])
  useEffect(() => {
    const evidence = new URLSearchParams(location.search).get('evidence')
    if (!evidence) return
    let active = true
    void getEvidence(evidence)
      .then((entry) => {
        if (active && entry?.record.analysis) {
          const result = entry.record.analysis
          setLast(result)
          if (result.samples) {
            setPhotometry(result)
            setTab('photometry')
          } else if (result.counterparts) {
            setCatalog(result)
            setTab('photometry')
          } else if (result.measurements) {
            setTrack(result)
            setTab('images')
          } else {
            setImage(result)
            setTab('images')
          }
          setMessage('Reopened recorded evidence ' + evidence)
        }
      })
      .catch((reason) => {
        if (active) setError(String(reason))
      })
    return () => {
      active = false
    }
  }, [])
  async function run(
    kind: ScienceParameters['kind'],
    saved?: ScienceParameters,
  ) {
    controller.current?.abort()
    const active = new AbortController()
    controller.current = active
    const id = ++generation.current
    setBusy(true)
    setError('')
    setMessage('')
    setJob(null)
    const parameters = saved ?? {
      kind,
      ids: frames.map((frame) => frame.id),
      ...source,
      radiusArcsec: radius,
      epochDays: days,
      background,
      eastRate: east,
      northRate: north,
    }
    try {
      const result = await runAnalysis(parameters, active.signal, setJob)
      if (id !== generation.current || active.signal.aborted) return
      setLast(result)
      onResult(result)
      if (kind === 'photometry' || kind === 'spectrum') {
        setPhotometry(result)
        setTab('photometry')
      } else if (kind === 'catalog') {
        setCatalog(result)
      } else if (kind === 'track') {
        setTrack(result)
        if (result.fit) {
          setEast(result.fit.eastArcsecPerYear)
          setNorth(result.fit.northArcsecPerYear)
        }
      } else {
        setImage(result)
        setTab('images')
      }
    } catch (reason) {
      if (id === generation.current && (reason as Error).name !== 'AbortError')
        setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      if (id === generation.current) {
        setBusy(false)
        setJob(null)
      }
    }
  }
  async function save() {
    if (!last) return
    try {
      const result = await saveEvidence({ target, note, analysis: last })
      const url = new URL(location.href)
      url.searchParams.set('evidence', result.id)
      history.replaceState({}, '', url)
      setMessage(
        `Saved evidence ${result.id}. This page URL reopens the recorded analysis.`,
      )
    } catch (reason) {
      setError(String(reason))
    }
  }
  async function assess(id: string, verdict: string) {
    try {
      await assessEvidence(id, reviewer, verdict, reviewNote)
      setEntries((await listEvidence()).entries)
      setReviewNote('')
      setMessage(
        'Your assessment was saved. A later assessment updates your earlier one.',
      )
    } catch (reason) {
      setError(String(reason))
    }
  }
  function reopen(entry: EvidenceEntry) {
    const result = entry.record.analysis
    if (!result) return
    setLast(result)
    setMessage(
      `Recorded source RA ${result.position.raDeg.toFixed(5)}°, Dec ${result.position.decDeg.toFixed(5)}°`,
    )
    if (result.samples) {
      setPhotometry(result)
      setTab('photometry')
    } else if (result.counterparts) {
      setCatalog(result)
      setTab('photometry')
    } else if (result.measurements) {
      setTrack(result)
      setTab('images')
    } else {
      setImage(result)
      setTab('images')
    }
  }
  const availableChannels = [
    ...new Set(
      (photometry?.samples ?? [])
        .map((point) => point.channel)
        .filter((value): value is number => value !== null),
    ),
  ].sort((a, b) => a - b)
  const activeChannel =
    channel !== null && availableChannels.includes(channel)
      ? channel
      : availableChannels[0]
  return (
    <section className="science-workspace" aria-label="Science workspace">
      <div className="science-tabs" role="group" aria-label="Science tools">
        {(['photometry', 'images', 'atlas', 'review'] as Tab[]).map((value) => (
          <button
            key={value}
            aria-pressed={tab === value}
            className={tab === value ? 'active' : ''}
            onClick={() => {
              setTab(value)
              setError('')
            }}
          >
            {value === 'photometry'
              ? 'Light curves'
              : value === 'images'
                ? 'Image processing'
                : value === 'atlas'
                  ? 'Sky atlas'
                  : 'Evidence & review'}
          </button>
        ))}
      </div>
      {busy && (
        <div className="analysis-progress" role="status">
          <span>
            {job?.message ?? 'Submitting analysis'} · {job?.completed ?? 0}/
            {job?.total || '…'}
          </span>
          <button onClick={() => controller.current?.abort()}>Cancel</button>
        </div>
      )}
      {error && (
        <p className="inline-warning" role="alert">
          {error}
        </p>
      )}
      {message && (
        <p className="science-message" role="status">
          {message}
        </p>
      )}
      {tab === 'atlas' ? (
        <SkyAtlas target={target} onNavigate={onNavigate} />
      ) : (
        <div className="science-body">
          {tab !== 'review' && (
            <div className="source-summary">
              <strong>
                {source ? 'Selected source' : 'Choose a source to analyse'}
              </strong>
              <span>
                {frames.length} available exposures · native FITS measurements
              </span>
              <button className="secondary-button" onClick={onSelectSource}>
                {source ? 'Change selection' : 'Select a source in the image'}
              </button>
            </div>
          )}
          {tab === 'photometry' && (
            <>
              <div className="science-controls">
                <label>
                  Aperture radius{' '}
                  <input
                    aria-label="Aperture radius in arcseconds"
                    type="number"
                    min={4}
                    max={60}
                    value={radius}
                    onChange={(event) => setRadius(Number(event.target.value))}
                  />{' '}
                  arcsec
                </label>
                <label>
                  Time bins{' '}
                  <select
                    aria-label="Light curve time bins"
                    value={days}
                    onChange={(event) => setDays(Number(event.target.value))}
                  >
                    {[1, 7, 30, 180].map((value) => (
                      <option key={value} value={value}>
                        {value} days
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              <div className="science-actions">
                <button
                  className="primary-button"
                  disabled={!source || busy}
                  onClick={() => void run('photometry')}
                >
                  Measure light curve
                </button>
                <button
                  className="secondary-button"
                  disabled={!source || busy}
                  onClick={() => void run('spectrum')}
                >
                  Extract six-detector spectrum
                </button>
                <button
                  className="secondary-button"
                  disabled={!source || busy}
                  onClick={() => void run('catalog')}
                >
                  Check Gaia counterpart
                </button>
              </div>
              {catalog && (
                <div className="science-motion-fit">
                  <strong>Nearby Gaia DR3 catalog entries</strong>
                  {catalog.counterparts?.length ? (
                    catalog.counterparts.map((row) => (
                      <p key={row.id}>
                        {row.label ?? row.id} ·{' '}
                        {row.separationArcsec.toFixed(2)} arcsec away
                      </p>
                    ))
                  ) : (
                    <p>No nearby catalog entries were returned.</p>
                  )}
                </div>
              )}
              {photometry && (
                <>
                  <p className="science-result-heading">
                    {photometry.samples?.length ?? 0} measurements · RA{' '}
                    {photometry.position.raDeg.toFixed(5)}°, Dec{' '}
                    {photometry.position.decDeg.toFixed(5)}° · aperture{' '}
                    {photometry.provenance.parameters.radiusArcsec} arcsec
                  </p>
                  {availableChannels.length > 0 ? (
                    <>
                      <label className="field-label">
                        Wavelength channel{' '}
                        <select
                          aria-label="Light curve wavelength channel"
                          className="inspector-select"
                          value={activeChannel}
                          onChange={(event) =>
                            setChannel(Number(event.target.value))
                          }
                        >
                          {availableChannels.map((value) => (
                            <option key={value} value={value}>
                              Channel {value} ·{' '}
                              {
                                photometry.samples?.filter(
                                  (point) => point.channel === value,
                                ).length
                              }{' '}
                              observations
                            </option>
                          ))}
                        </select>
                      </label>
                      <LightCurve
                        points={photometry.samples ?? []}
                        channel={activeChannel}
                      />
                    </>
                  ) : (
                    <p>
                      No valid aperture measurements were available at this
                      position.
                    </p>
                  )}
                  {photometry.provenance.parameters.kind === 'spectrum' && (
                    <>
                      <h3>Aperture spectrum across available detectors</h3>
                      <SpectrumPlot
                        data={{
                          samples: photometry.samples ?? [],
                          fluxUnit: 'mJy',
                        }}
                      />
                    </>
                  )}
                  <WavelengthTime result={photometry} onChannel={setChannel} />
                  <div className="channel-statistics">
                    {photometry.channels?.map((row) => (
                      <span key={row.channel}>
                        Channel {row.channel} · {row.count} samples · reduced χ²{' '}
                        {row.reducedChiSquare?.toFixed(2) ??
                          'requires another epoch'}
                      </span>
                    ))}
                  </div>
                  <button
                    className="secondary-button"
                    disabled={!photometry.samples?.length}
                    onClick={() =>
                      download(
                        pointCsv(photometry.samples ?? []),
                        'spherex-photometry.csv',
                        'text/csv',
                      )
                    }
                  >
                    Export measurements CSV
                  </button>
                </>
              )}
            </>
          )}
          {tab === 'images' && (
            <>
              <div className="science-controls">
                <label>
                  Sky background{' '}
                  <select
                    aria-label="Processing background model"
                    value={background}
                    onChange={(event) =>
                      setBackground(event.target.value as typeof background)
                    }
                  >
                    <option value="none">Preserve background</option>
                    <option value="constant">Robust constant</option>
                    <option value="plane">Robust spatial plane</option>
                  </select>
                </label>
              </div>
              <div className="science-actions">
                <button
                  className="secondary-button"
                  disabled={!source || busy}
                  onClick={() => void run('stack')}
                >
                  Weighted channel stack
                </button>
                <button
                  className="secondary-button"
                  disabled={!source || busy}
                  onClick={() => void run('difference')}
                >
                  PSF-aware difference
                </button>
                <button
                  className="secondary-button"
                  disabled={!source || busy}
                  onClick={() => void run('track')}
                >
                  Fit source motion
                </button>
              </div>
              {track && (
                <div className="science-motion-fit">
                  <strong>
                    {track.measurements?.length ?? 0} associated positions
                  </strong>
                  {track.fit && (
                    <>
                      <p>
                        East {track.fit.eastArcsecPerYear.toFixed(2)} ±{' '}
                        {track.fit.rateUncertaintyArcsecPerYear.toFixed(2)}{' '}
                        arcsec/year
                      </p>
                      <p>
                        North {track.fit.northArcsecPerYear.toFixed(2)} ±{' '}
                        {track.fit.rateUncertaintyArcsecPerYear.toFixed(2)}{' '}
                        arcsec/year
                      </p>
                      <small>
                        Assumed astrometric floor{' '}
                        {track.fit.assumedAstrometricFloorArcsec} arcsec. Linear
                        motion requires independent validation.
                      </small>
                    </>
                  )}
                  {track.warnings.map((warning, i) => (
                    <p className="control-hint" key={i}>
                      {warning}
                    </p>
                  ))}
                </div>
              )}
              <div className="science-controls">
                <label>
                  East motion{' '}
                  <input
                    aria-label="East motion in arcseconds per year"
                    type="number"
                    min={-1000}
                    max={1000}
                    value={east}
                    onChange={(event) => setEast(Number(event.target.value))}
                  />
                </label>
                <label>
                  North motion{' '}
                  <input
                    aria-label="North motion in arcseconds per year"
                    type="number"
                    min={-1000}
                    max={1000}
                    value={north}
                    onChange={(event) => setNorth(Number(event.target.value))}
                  />
                </label>
                <span>arcsec/year</span>
              </div>
              <button
                className="primary-button"
                disabled={!source || busy}
                onClick={() => void run('shift-stack')}
              >
                Stack along this motion
              </button>
              {image && (
                <>
                  <p className="science-result-heading">
                    Channel {image.channel}{' '}
                    {image.inputCount
                      ? `· ${image.inputCount} exposures · ${image.rejectedPixels ?? 0} outlier pixels rejected`
                      : ''}
                  </p>
                  <div className="science-images">
                    {image.imageUrl && (
                      <figure>
                        <img
                          src={imageURL(image.imageUrl)}
                          alt="Variance-aware processed SPHEREx observations"
                        />
                        <figcaption>Processed observations</figcaption>
                      </figure>
                    )}
                    {image.staticImageUrl && (
                      <figure>
                        <img
                          src={imageURL(image.staticImageUrl)}
                          alt="Stationary weighted stack for comparison"
                        />
                        <figcaption>Stationary stack</figcaption>
                      </figure>
                    )}
                    {image.significanceUrl && (
                      <figure>
                        <img
                          src={imageURL(image.significanceUrl)}
                          alt="Statistical significance map from propagated image variance"
                        />
                        <figcaption>
                          Statistical signal / error · red positive, blue
                          negative
                        </figcaption>
                      </figure>
                    )}
                  </div>
                </>
              )}
            </>
          )}
          {tab === 'review' && (
            <>
              <p className="section-explainer">
                Saved analyses retain observation checksums, processing
                settings, and calibration versions. Reviews are local browser
                assessments and require expert verification.
              </p>
              <label className="field-label">
                Assessment note{' '}
                <textarea
                  aria-label="Evidence assessment note"
                  value={reviewNote}
                  maxLength={2000}
                  onChange={(event) => setReviewNote(event.target.value)}
                  className="note-input"
                />
              </label>
              {!entries.length && (
                <p>
                  No evidence has been submitted yet. Save a completed analysis
                  to begin.
                </p>
              )}
              {entries.map((entry) => (
                <article className="evidence-card" key={entry.id}>
                  <strong>
                    {entry.record.target?.name ?? 'Sky field'} ·{' '}
                    {new Date(entry.createdAt).toLocaleDateString()}
                  </strong>
                  <p>{entry.record.note || entry.record.analysis?.method}</p>
                  <small>Evidence {entry.id}</small>
                  <div className="science-actions">
                    <button
                      className="secondary-button"
                      onClick={() => reopen(entry)}
                    >
                      Reopen recorded analysis
                    </button>
                    {entry.record.analysis && (
                      <button
                        className="secondary-button"
                        disabled={busy}
                        onClick={() =>
                          void run(
                            entry.record.analysis!.provenance.parameters.kind,
                            entry.record.analysis!.provenance.parameters,
                          )
                        }
                      >
                        Rerun recorded settings
                      </button>
                    )}
                    {entry.record.target && (
                      <button
                        className="secondary-button"
                        onClick={() => onNavigate(entry.record.target!)}
                      >
                        Load recorded sky field
                      </button>
                    )}
                  </div>
                  <div className="review-verdicts">
                    {(
                      [
                        'possible-motion',
                        'possible-variability',
                        'artifact',
                        'uncertain',
                      ] as const
                    ).map((verdict) => (
                      <button
                        key={verdict}
                        onClick={() => void assess(entry.id, verdict)}
                      >
                        {verdict.replaceAll('-', ' ')} ·{' '}
                        {entry.assessments[verdict] ?? 0}
                      </button>
                    ))}
                  </div>
                </article>
              ))}
            </>
          )}
          {last && tab !== 'review' && (
            <div className="science-evidence">
              <h3>Evidence and processing</h3>
              <p className="control-hint">{last.method}</p>
              {last.warnings.map((warning, i) => (
                <p className="quality-warning" key={i}>
                  {warning}
                </p>
              ))}
              <details className="processing-notes">
                <summary>Observation and calibration provenance</summary>
                <pre>{JSON.stringify(last.provenance, null, 2)}</pre>
              </details>
              <label className="field-label">
                Evidence note{' '}
                <textarea
                  aria-label="Analysis evidence note"
                  className="note-input"
                  value={note}
                  maxLength={2000}
                  onChange={(event) => setNote(event.target.value)}
                />
              </label>
              <div className="science-actions">
                <button
                  className="secondary-button"
                  onClick={() => void save()}
                >
                  Save analysis for review
                </button>
                <button
                  className="secondary-button"
                  onClick={() =>
                    download(
                      JSON.stringify({ target, note, analysis: last }, null, 2),
                      'spherex-evidence.json',
                      'application/json',
                    )
                  }
                >
                  Download evidence JSON
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </section>
  )
}
