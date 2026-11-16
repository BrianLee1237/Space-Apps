import { useEffect, useRef, useState } from 'react'
import type { MouseEvent } from 'react'
import { Maximize, Minus, Plus, RotateCcw, ImageOff } from 'lucide-react'
import { imageURL } from '../services/api'
import type {
  Candidate,
  ImageLocation,
  MotionTrack,
  Observation,
  OverlayResponse,
} from '../types/astronomy'

type Props = {
  frame: Observation | null
  track: MotionTrack | null
  differenceUrl?: string
  combineUrl?: string
  status: 'idle' | 'loading' | 'ready' | 'empty' | 'error'
  error: string
  candidates: Candidate[]
  gaia: OverlayResponse | null
  brightness: number
  contrast: number
  inverted: boolean
  onInspect: (p: ImageLocation) => void
  onCandidate: (c: Candidate) => void
  onFrameReady?: (id: string) => void
}
export default function SkyViewer({
  frame,
  track,
  differenceUrl,
  combineUrl,
  status,
  error,
  candidates,
  gaia,
  brightness,
  contrast,
  inverted,
  onInspect,
  onCandidate,
  onFrameReady,
}: Props) {
  const root = useRef<HTMLDivElement>(null),
    image = useRef<HTMLImageElement>(null)
  const [zoomState, setZoom] = useState({ source: '', factor: 1 }),
    [failedSource, setFailedSource] = useState<string | null>(null)
  const [retry, setRetry] = useState({ source: '', attempt: 0 })
  const [loadedSource, setLoadedSource] = useState<string | null>(null)
  const overlayUrl = differenceUrl || combineUrl
  const imageSrc = overlayUrl
    ? imageURL(overlayUrl)
    : frame?.imageUrl
      ? imageURL(frame.imageUrl)
      : null
  const attempt = retry.source === imageSrc ? retry.attempt : 0
  const requestSrc =
    imageSrc && attempt > 0
      ? `${imageSrc}${imageSrc.includes('?') ? '&' : '?'}retry=${attempt}`
      : imageSrc
  const imageFailed = !!requestSrc && failedSource === requestSrc
  const imageLoaded = loadedSource === requestSrc
  const zoom = zoomState.source === imageSrc ? zoomState.factor : 1
  const show = !!imageSrc && !imageFailed
  useEffect(() => {
    if (!imageFailed || !imageSrc || attempt >= 2) return
    const timer = window.setTimeout(
      () => setRetry({ source: imageSrc, attempt: attempt + 1 }),
      1000 * 2 ** attempt,
    )
    return () => window.clearTimeout(timer)
  }, [imageFailed, imageSrc, attempt])
  function pick(e: MouseEvent<HTMLImageElement>) {
    if (!frame || overlayUrl || !image.current || !image.current.naturalWidth)
      return
    const node = image.current
    const box = node.getBoundingClientRect()
    const nativeRatio = node.naturalWidth / node.naturalHeight,
      boxRatio = box.width / box.height
    const actualWidth =
      boxRatio > nativeRatio ? box.height * nativeRatio : box.width
    const actualHeight =
      boxRatio > nativeRatio ? box.height : box.width / nativeRatio
    const x =
      (e.clientX - (box.left + (box.width - actualWidth) / 2)) / actualWidth
    const y =
      (e.clientY - (box.top + (box.height - actualHeight) / 2)) / actualHeight
    if (x < 0 || x > 1 || y < 0 || y > 1) return
    onInspect({ xFraction: x, yFraction: y })
  }
  async function fullscreen() {
    if (!root.current) return
    if (document.fullscreenElement) await document.exitFullscreen()
    else await root.current.requestFullscreen()
  }
  return (
    <section
      className="sky-viewer"
      ref={root}
      aria-label="SPHEREx image viewer"
      aria-busy={show && !imageLoaded}
    >
      {frame && (
        <div className="viewer-tag">
          <span>
            {differenceUrl
              ? 'Difference image'
              : combineUrl
                ? 'Combined exposure'
                : 'SPHEREx observation'}
          </span>
          {!overlayUrl && (
            <span>
              {new Date(frame.observedAt).toLocaleString(undefined, {
                dateStyle: 'medium',
                timeStyle: 'short',
              })}
            </span>
          )}
        </div>
      )}
      <div className="viewer-tools" aria-label="Image zoom controls">
        <button
          title="Zoom in"
          aria-label="Zoom in"
          disabled={!show}
          type="button"
          onClick={() =>
            setZoom({
              source: imageSrc ?? '',
              factor: Math.min(5, +(zoom + 0.25).toFixed(2)),
            })
          }
        >
          <Plus size={17} />
        </button>
        <button
          title="Zoom out"
          aria-label="Zoom out"
          disabled={!show}
          type="button"
          onClick={() =>
            setZoom({
              source: imageSrc ?? '',
              factor: Math.max(1, +(zoom - 0.25).toFixed(2)),
            })
          }
        >
          <Minus size={17} />
        </button>
        <button
          title="Reset zoom"
          aria-label="Reset zoom"
          disabled={!show}
          type="button"
          onClick={() => setZoom({ source: imageSrc ?? '', factor: 1 })}
        >
          <RotateCcw size={16} />
        </button>
        <button
          title="Fullscreen"
          aria-label="Fullscreen"
          type="button"
          onClick={() => void fullscreen()}
        >
          <Maximize size={16} />
        </button>
      </div>
      {show && (
        <div className="sky-image-container">
          <div
            className="sky-image-layer"
            style={{ transform: `scale(${zoom})` }}
          >
            <div className="sky-image-content">
              <img
                ref={image}
                src={requestSrc!}
                className="sky-image"
                alt={
                  differenceUrl
                    ? 'Difference image produced by the backend'
                    : combineUrl
                      ? 'Combined exposure produced by the backend'
                      : 'SPHEREx observation returned by the backend'
                }
                onError={() => setFailedSource(requestSrc)}
                onLoad={() => {
                  setLoadedSource(requestSrc)
                  if (frame && !overlayUrl) onFrameReady?.(frame.id)
                }}
                onClick={pick}
                draggable={false}
                style={{
                  filter: `brightness(${brightness}%) contrast(${contrast}%) ${inverted ? 'invert(1)' : ''}`,
                }}
              />
              {!combineUrl && (
                <>
                  {' '}
                  {candidates.length > 0 && (
                    <svg
                      className="motion-arrows"
                      viewBox="0 0 100 100"
                      preserveAspectRatio="none"
                      aria-hidden="true"
                    >
                      <defs>
                        <marker
                          id="motion-arrow"
                          markerWidth="4"
                          markerHeight="4"
                          refX="3"
                          refY="2"
                          orient="auto"
                        >
                          <path d="M0,0 L4,2 L0,4" fill="var(--accent)" />
                        </marker>
                      </defs>
                      {candidates
                        .filter((c) => c.previousXFraction !== undefined)
                        .map((c) => (
                          <line
                            key={c.id}
                            x1={c.previousXFraction! * 100}
                            y1={c.previousYFraction! * 100}
                            x2={c.xFraction! * 100}
                            y2={c.yFraction! * 100}
                            stroke="var(--accent)"
                            strokeWidth=".45"
                            markerEnd="url(#motion-arrow)"
                          />
                        ))}
                    </svg>
                  )}
                  {candidates
                    .filter(
                      (c) =>
                        c.xFraction !== undefined && c.yFraction !== undefined,
                    )
                    .map((candidate, i) => {
                      const nearby = candidates
                        .slice(0, i)
                        .filter(
                          (other) =>
                            Math.abs(
                              (other.xFraction ?? 0) - candidate.xFraction!,
                            ) < 0.4 &&
                            Math.abs(
                              (other.yFraction ?? 0) - candidate.yFraction!,
                            ) < 0.09,
                        ).length
                      const captionStyle = {
                        top: -30 + nearby * 32,
                        ...(candidate.xFraction! > 0.55
                          ? { right: 15, left: 'auto' }
                          : { left: 15, right: 'auto' }),
                      }
                      return (
                        <button
                          key={candidate.id}
                          className="sky-marker candidate-marker"
                          title={
                            candidate.caption ||
                            candidate.notes ||
                            candidate.label
                          }
                          aria-label={`Inspect unverified candidate ${candidate.label || candidate.id}`}
                          type="button"
                          style={{
                            left: `${candidate.xFraction! * 100}%`,
                            top: `${candidate.yFraction! * 100}%`,
                          }}
                          onClick={(event) => {
                            event.stopPropagation()
                            onCandidate(candidate)
                          }}
                        >
                          <span className="marker-caption" style={captionStyle}>
                            {candidate.label} ·{' '}
                            {candidate.displacementArcsec
                              ? `${candidate.displacementArcsec.toFixed(1)}″ shift`
                              : candidate.brightnessChange! > 0
                                ? 'Positive residual'
                                : 'Negative residual'}
                          </span>
                        </button>
                      )
                    })}
                </>
              )}
              {!overlayUrl && track && track.measurements.length > 0 && (
                <svg
                  className="motion-track-overlay"
                  viewBox="0 0 100 100"
                  preserveAspectRatio="none"
                  role="img"
                  aria-label={`Unverified measured positions across ${track.measurements.length} observations`}
                >
                  {track.measurements.length > 1 && (
                    <polyline
                      points={track.measurements
                        .map((p) => `${p.xFraction * 100},${p.yFraction * 100}`)
                        .join(' ')}
                      fill="none"
                      stroke="var(--data)"
                      strokeWidth=".2"
                      strokeDasharray=".6 .45"
                    />
                  )}
                  {track.measurements.map((p, i) => (
                    <g key={p.observationId}>
                      <circle
                        cx={p.xFraction * 100}
                        cy={p.yFraction * 100}
                        r={frame?.id === p.observationId ? 0.9 : 0.45}
                        stroke={
                          frame?.id === p.observationId
                            ? 'var(--accent)'
                            : 'var(--data)'
                        }
                        fill="none"
                        strokeWidth=".22"
                      />
                      <title>{`Epoch ${i + 1}: ${p.observedAt}, RA ${p.raDeg.toFixed(6)}°, Dec ${p.decDeg.toFixed(6)}°`}</title>
                    </g>
                  ))}
                </svg>
              )}
              {!overlayUrl &&
                gaia?.sources
                  .filter(
                    (s) =>
                      s.xFraction >= 0 &&
                      s.xFraction <= 1 &&
                      s.yFraction >= 0 &&
                      s.yFraction <= 1,
                  )
                  .map((s) => (
                    <span
                      key={s.id}
                      title={s.label || `Gaia DR3 source ${s.id}`}
                      className="sky-marker gaia-marker"
                      style={{
                        left: `${s.xFraction * 100}%`,
                        top: `${s.yFraction * 100}%`,
                      }}
                    />
                  ))}
            </div>
          </div>
        </div>
      )}
      {show && !imageLoaded && (
        <div className="image-loading-state" role="status">
          Loading selected exposure…
        </div>
      )}
      {!show && (
        <div className="viewer-empty" role="status">
          {status === 'loading' ? (
            <div className="loading-indicator" />
          ) : (
            <ImageOff size={35} strokeWidth={1.4} />
          )}
          <strong>
            {status === 'loading'
              ? 'Loading data'
              : status === 'error'
                ? 'Unable to load data'
                : imageFailed
                  ? 'Unable to display image'
                  : 'No data'}
          </strong>
          <span>
            {status === 'loading'
              ? 'Retrieving real SPHEREx observations'
              : status === 'error'
                ? error
                : imageFailed
                  ? attempt < 2
                    ? 'Retrying the archive image…'
                    : 'This exposure is unavailable. Retry it or choose another epoch.'
                  : status === 'empty'
                    ? 'No observations returned for this search.'
                    : 'Enter coordinates to load observations.'}
          </span>
          {imageFailed && (
            <button
              type="button"
              className="secondary-button"
              onClick={() =>
                setRetry({ source: imageSrc!, attempt: attempt + 1 })
              }
            >
              Retry image
            </button>
          )}
        </div>
      )}
      {frame && (
        <div className="viewer-bottom-info">
          {frame.release && <span>{frame.release}</span>}
          {frame.detector && <span>Detector {frame.detector}</span>}
          {frame.channel && <span>Channel {frame.channel}</span>}
          {frame.flags && frame.flags.length > 0 && (
            <span>
              {frame.flags.length} quality flag
              {frame.flags.length === 1 ? '' : 's'}
            </span>
          )}
          {zoom !== 1 && <span>Zoom {zoom.toFixed(2)}×</span>}
        </div>
      )}
    </section>
  )
}
