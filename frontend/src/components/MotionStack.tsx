import { useEffect, useMemo, useRef, useState } from 'react'
import type { PointerEvent } from 'react'
import {
  displayLimits, expectedOffsets, injectPractice, linearPath, loadMotionDataset,
  PRACTICE_RANGE, scanPractice, stackImages, timeFractions, ZERO,
} from '../features/motionStack'
import type { MotionDataset, Point } from '../features/motionStack'
import './MotionStack.css'

const IRSA = 'https://irsa.ipac.caltech.edu/data/SPHEREx/docs/comet3iatlas/index.html'
const NASA = 'https://science.nasa.gov/photojournal/nasas-spherex-examines-comet-3i-atlass-coma/'
const WEBB = 'https://science.nasa.gov/asset/webb/interstellar-comet-3i-atlas-nirspec-ifu/'
const NASA_IMAGE = 'https://assets.science.nasa.gov/dynamicimage/assets/science/psd/photojournal/pia/pia26/pia26720/PIA26720_SPHEREx_3I_4panel_colorized.png?fit=clip&w=1000'
const PRACTICE_PATHS: Point[] = [
  [-24, 16], [24, 16], [-24, -16], [24, -16],
  [-16, 24], [16, -24], [24, 24], [-24, -24],
]
type Mode = 'comet' | 'practice'
type PathType = 'expected' | 'opposite' | 'manual'

function StackImage({ pixels, size, limits, label, showCenter }: {
  pixels: Float32Array
  size: number
  limits: Point
  label: string
  showCenter?: boolean
}) {
  const canvas = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    const ctx = canvas.current?.getContext('2d')
    if (!ctx) return
    const image = ctx.createImageData(size, size)
    const [low, high] = limits
    const stretch = Math.asinh(10)
    pixels.forEach((value, i) => {
      if (!Number.isFinite(value)) return
      const normalized = Math.max(0, Math.min(1, (value - low) / (high - low)))
      const intensity = Math.round(255 * Math.asinh(10 * normalized) / stretch)
      const offset = i * 4
      image.data[offset] = intensity
      image.data[offset + 1] = intensity
      image.data[offset + 2] = intensity
      image.data[offset + 3] = 255
    })
    ctx.putImageData(image, 0, 0)
  }, [pixels, size, limits])

  return <figure className="motion-image">
    <figcaption>{label}</figcaption>
    <div className="motion-image-plane">
      <canvas ref={canvas} role="img" aria-label={label} width={size} height={size} />
      {showCenter && <span className="motion-center" aria-hidden="true" />}
    </div>
  </figure>
}

function VectorControl({ motion, range, scale, onChange }: {
  motion: Point
  range: number
  scale: number
  onChange: (motion: Point) => void
}) {
  const [dx, dy] = motion
  function change(event: PointerEvent<HTMLDivElement>) {
    const bounds = event.currentTarget.getBoundingClientRect()
    function coordinate(position: number, origin: number, length: number) {
      return Math.max(-range, Math.min(range, Math.round(((position - origin) / length * 2 - 1) * range)))
    }
    onChange([coordinate(event.clientX, bounds.left, bounds.width), coordinate(event.clientY, bounds.top, bounds.height)])
  }

  return <div className="motion-vector">
    <div className="motion-vector-plane" aria-hidden="true"
      onPointerDown={event => {
        event.currentTarget.setPointerCapture(event.pointerId)
        change(event)
      }}
      onPointerMove={event => {
        if (event.currentTarget.hasPointerCapture(event.pointerId)) change(event)
      }}>
      <svg viewBox="-52 -52 104 104">
        <path d="M -50 0 H 50 M 0 -50 V 50" className="motion-axes" />
        <line x1="0" y1="0" x2={dx / range * 48} y2={dy / range * 48} className="motion-arrow" />
        <circle cx={dx / range * 48} cy={dy / range * 48} r="3" className="motion-vector-tip" />
      </svg>
      <span className="motion-north">N</span><span className="motion-east">E</span>
    </div>
    <div className="motion-sliders">
      <label>East / west displacement
        <input type="range" min={-range} max={range} value={-dx}
          aria-valuetext={`${Math.abs(dx * scale).toFixed(0)} arcseconds ${dx > 0 ? 'west' : 'east'}`}
          onChange={event => onChange([-Number(event.target.value), dy])} />
      </label>
      <label>North / south displacement
        <input type="range" min={-range} max={range} value={-dy}
          aria-valuetext={`${Math.abs(dy * scale).toFixed(0)} arcseconds ${dy > 0 ? 'south' : 'north'}`}
          onChange={event => onChange([dx, -Number(event.target.value)])} />
      </label>
      <output>{Math.hypot(dx, dy) * scale < 0.5 ? 'No shift' : `${(Math.hypot(dx, dy) * scale).toFixed(0)}″ total shift`}</output>
    </div>
  </div>
}

function Chemistry() {
  return <details className="motion-chemistry">
    <summary>Explore the comet’s chemistry</summary>
    <div className="motion-chemistry-grid">
      <a href={NASA} target="_blank" rel="noreferrer">
        <img src={NASA_IMAGE} loading="lazy" alt="Published December SPHEREx images of dust, water, organics, and carbon dioxide around 3I/ATLAS" />
      </a>
      <div>
        <h3>SPHEREx · December 2025</h3>
        <p>NASA’s published maps show how dust, water, organics, and carbon dioxide look at different infrared wavelengths. NASA/JPL-Caltech.</p>
        <a href={NASA} target="_blank" rel="noreferrer">View the SPHEREx maps at NASA ↗</a>
        <a href="https://science.nasa.gov/blogs/3iatlas/2026/02/04/nasas-spherex-mission-tracks-brightening-of-interstellar-comet/" target="_blank" rel="noreferrer">Compare the August and December campaigns ↗</a>
        <a href={WEBB} target="_blank" rel="noreferrer">See Webb’s December 22–23 molecular maps ↗</a>
      </div>
    </div>
  </details>
}

function Experiment({ data, mode }: { data: MotionDataset; mode: Mode }) {
  const [motion, setMotion] = useState<Point>(ZERO)
  const [pathType, setPathType] = useState<PathType>('expected')
  const [truth, setTruth] = useState(() => PRACTICE_PATHS[Math.floor(Math.random() * PRACTICE_PATHS.length)])
  const [revealedError, setRevealedError] = useState<number | null>(null)
  const [scan, setScan] = useState<ReturnType<typeof scanPractice> | null>(null)
  const [frameIndex, setFrameIndex] = useState<number | null>(null)
  const practice = mode === 'practice'
  const size = data.size
  const scale = practice ? data.practiceArcsecPerPixel : data.arcsecPerPixel
  const range = practice ? PRACTICE_RANGE : Math.floor(size / 2 + 8)
  const fractions = useMemo(() => timeFractions(data.frames), [data])
  const offsets = useMemo(() => expectedOffsets(data), [data])
  const images = useMemo(() => practice ? injectPractice(data, fractions, truth) : data.comet,
    [practice, data, fractions, truth])
  const fixed = useMemo(() => stackImages(images, size, images.map(() => ZERO)), [images, size])
  const limits = useMemo<Point>(() => practice ? displayLimits(images) : [-0.13, 2.6], [images, practice])
  const registered = useMemo(() => {
    let path = linearPath(fractions, motion)
    if (!practice && pathType !== 'manual') {
      const sign = pathType === 'expected' ? 1 : -1
      path = offsets.map(([dx, dy]) => [sign * dx, sign * dy])
    }
    return stackImages(images, size, path)
  }, [fractions, motion, practice, pathType, offsets, images, size])

  function setTrial(next: Point) {
    setMotion(next)
    setPathType('manual')
    setRevealedError(null)
  }

  function reveal() {
    setRevealedError(Math.hypot(motion[0] - truth[0], motion[1] - truth[1]) * scale)
    setMotion(truth)
  }

  function newPractice() {
    const choices = PRACTICE_PATHS.filter(path => path !== truth)
    setTruth(choices[Math.floor(Math.random() * choices.length)])
    setTrial(ZERO)
    setScan(null)
    setFrameIndex(null)
  }

  const trialLabel = practice ? 'Your motion stack' : (
    pathType === 'expected' ? 'Stack along the comet’s path' : (
      pathType === 'opposite' ? 'Stack along the opposite path' : 'Stack along your path'
    )
  )
  const first = data.frames[0]
  const last = data.frames[data.frames.length - 1]
  const duration = (Date.parse(last.time) - Date.parse(first.time)) / 60000
  const direction = pathType === 'opposite' ? -1 : 1
  const activeMotion: Point = practice || pathType === 'manual' ? motion : [
    Math.round(direction * (last.position[0] - first.position[0])),
    Math.round(direction * (last.position[1] - first.position[1])),
  ]

  return <>
    <div className="motion-experiment">
      <div className="motion-views">
        <div className="motion-image-pair">
          <StackImage pixels={frameIndex === null ? fixed : images[frameIndex]} size={size} limits={limits}
            label={frameIndex === null ? 'Stack with stars fixed' : `Exposure ${frameIndex + 1} · stars fixed`} />
          <StackImage pixels={registered} size={size} limits={limits} label={trialLabel} showCenter />
        </div>
        <div className="motion-frames" role="group" aria-label="Left image">
          <button aria-pressed={frameIndex === null} onClick={() => setFrameIndex(null)}>Stack</button>
          {data.frames.map((frame, index) => <button key={frame.id} aria-pressed={frameIndex === index}
            onClick={() => setFrameIndex(index)} title={`${frame.time} · ${frame.wavelength.toFixed(3)} µm`}>
            {frame.time.slice(11, 19)} UTC
          </button>)}
        </div>
      </div>
      <aside className="motion-controls">
        <h2>{practice ? 'Find the simulated source' : 'Choose a path'}</h2>
        <p>{practice ? 'Adjust the direction and distance until the injected source sharpens inside the center ring.' :
          'Stack the same exposures along the predicted path, reverse it, or draw your own.'}</p>
        {!practice && <div className="motion-actions">
          <button aria-pressed={pathType === 'expected'} onClick={() => setPathType('expected')}>IRSA predicted path</button>
          <button aria-pressed={pathType === 'opposite'} onClick={() => setPathType('opposite')}>Opposite path</button>
        </div>}
        <VectorControl motion={activeMotion} range={range} scale={scale} onChange={setTrial} />
        {practice ? <>
          <div className="motion-actions">
            <button onClick={() => {
              const result = scanPractice(images, size, fractions)
              setScan(result)
              if (result.best) setTrial(result.best.motion)
            }}>Scan 81 paths</button>
            <button onClick={reveal} disabled={revealedError !== null}>Reveal injected path</button>
            <button onClick={newPractice}>New trial</button>
          </div>
          {revealedError !== null && <p className="motion-result" role="status">
            Your path was {revealedError.toFixed(1)}″ from the injected shift. The stack now uses the injected path.
          </p>}
        </> : <p className="motion-result">
          {data.frames.length} real exposures over {duration.toFixed(0)} minutes. Both images use the same brightness scale.
        </p>}
      </aside>
    </div>
    {scan && <section className="motion-scan">
      <h2>Path search</h2>
      <p>Each square tests a different east–west and north–south shift through the center. Brighter cells show greater local contrast in the two search exposures.</p>
      <div className="motion-heatmap" role="group" aria-label="Trial motion scores">
        {scan.trials.map(({ motion: point, score }) => {
          const max = scan.best?.score ?? 0
          const strength = max > 0 && Number.isFinite(score) ? Math.max(0, score / max) : 0
          const label = `East ${(-point[0] * scale).toFixed(0)}″, north ${(-point[1] * scale).toFixed(0)}″`
          return <button key={point.join(',')} type="button" aria-label={label} title={label}
            aria-pressed={point[0] === motion[0] && point[1] === motion[1]}
            style={{ backgroundColor: `hsl(37 68% ${12 + strength * 54}%)` }}
            onClick={() => setTrial(point)} />
        })}
      </div>
      <p role="status">{scan.best ? `Top path contrast: ${scan.best.score.toFixed(3)} MJy/sr in the search pair. ${Number.isFinite(scan.best.heldOut) ? `${scan.best.heldOut.toFixed(3)} MJy/sr in the two held-out exposures.` : 'The held-out exposures lack usable coverage.'}` : 'No path had enough valid image coverage.'}</p>
      <p>Contrast is the mean brightness near the candidate minus the surrounding background.</p>
    </section>}
    {!practice && <Chemistry />}
    <details className="motion-sources">
      <summary>Image sources and processing</summary>
      <p>SPHEREx QR2 detector 5 · December 14, 2025 · NASA/IPAC Infrared Science Archive.</p>
      <p>The cutouts use a shared sky grid and median background subtraction. The stacks average valid pixels with support from at least half the exposures. Wavelengths vary between images, so brightness differences also reflect spectral structure.</p>
      <ul>{data.frames.map(frame => <li key={frame.id}>
        <a href={frame.sourceUrl} target="_blank" rel="noreferrer">{frame.time.slice(11, 19)} UTC · {frame.wavelength.toFixed(3)} µm · {frame.id} ↗</a>
      </li>)}</ul>
      <a href={IRSA} target="_blank" rel="noreferrer">IRSA observation table and predicted positions ↗</a>
    </details>
  </>
}

export default function MotionStack() {
  const [mode, setMode] = useState<Mode>('comet')
  const [data, setData] = useState<MotionDataset | null>(null)
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    void loadMotionDataset(controller.signal).then(result => {
      if (!controller.signal.aborted) setData(result)
    }).catch(() => {
      if (!controller.signal.aborted) setError('Unable to load the archived observations.')
    })
    return () => controller.abort()
  }, [attempt])

  return <main className="motion-page">
    <div className="motion-content">
      <header className="motion-heading">
        <div>
          <h1>Shift &amp; Stack</h1>
          <p>{mode === 'comet' ? 'Follow interstellar comet 3I/ATLAS across real SPHEREx exposures.' :
            'Recover a simulated moving source placed in a real SPHEREx field.'}</p>
        </div>
        <div className="motion-mode" role="group" aria-label="Dataset">
          <button aria-pressed={mode === 'comet'} onClick={() => setMode('comet')}>3I/ATLAS</button>
          <button aria-pressed={mode === 'practice'} onClick={() => setMode('practice')}>Practice hunt</button>
        </div>
      </header>
      {data ? <Experiment key={mode} data={data} mode={mode} /> : error ?
        <div role="alert">{error} <button onClick={() => { setError(''); setAttempt(value => value + 1) }}>Retry</button></div> :
        <p role="status">Loading SPHEREx exposures…</p>}
    </div>
  </main>
}
