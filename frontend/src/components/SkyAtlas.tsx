import { useEffect, useRef, useState } from 'react'
import type { SearchTarget } from '../types/astronomy'
import { request } from '../services/api'

type Channel = { index: number; WAVELENGTH: number; detector: number }
export default function SkyAtlas({
  target,
  onNavigate,
}: {
  target: SearchTarget | null
  onNavigate: (target: SearchTarget) => void
}) {
  const host = useRef<HTMLIFrameElement>(null)
  const [channel, setChannel] = useState(86),
    [channels, setChannels] = useState<Channel[]>([])
  const [error, setError] = useState(''),
    [ready, setReady] = useState(false)
  const [picked, setPicked] = useState<{ ra: number; dec: number } | null>(null)
  useEffect(() => {
    void request<{ channels: Channel[] }>('/science/channels')
      .then((data) => setChannels(data.channels))
      .catch(() => {})
  }, [])
  useEffect(() => {
    const receive = (event: MessageEvent) => {
      if (
        event.origin !== location.origin ||
        event.source !== host.current?.contentWindow
      )
        return
      if (event.data?.type === 'atlas-ready') setReady(true)
      if (event.data?.type === 'atlas-error')
        setError(String(event.data.message))
      if (
        event.data?.type === 'atlas-picked' &&
        Number.isFinite(event.data.ra) &&
        Number.isFinite(event.data.dec)
      )
        setPicked({ ra: event.data.ra, dec: event.data.dec })
    }
    window.addEventListener('message', receive)
    return () => window.removeEventListener('message', receive)
  }, [])
  useEffect(() => {
    host.current?.contentWindow?.postMessage(
      {
        type: 'atlas-config',
        channel,
        ra: target?.raDeg ?? 0,
        dec: target?.decDeg ?? 0,
        fov: Math.max(0.2, (target?.fovArcmin ?? 60) / 60),
      },
      location.origin,
    )
  }, [channel, target, ready])
  return (
    <div className="sky-atlas">
      <div className="science-controls">
        <label>
          Infrared channel{' '}
          <select
            aria-label="Atlas wavelength channel"
            value={channel}
            onChange={(event) => setChannel(Number(event.target.value))}
          >
            {channels.map((row) => (
              <option key={row.index} value={row.index}>
                {row.index} · {row.WAVELENGTH.toFixed(3)} µm · D{row.detector}
              </option>
            ))}
          </select>
        </label>
        <span>{ready ? 'SPHEREx DR1 mosaic' : 'Loading IRSA mosaic…'}</span>
      </div>
      {(channel === 51 || channel === 52) && (
        <p className="quality-warning">
          IRSA marks this dichroic layer as blank in the all-sky visualization.
        </p>
      )}
      {error && (
        <p className="inline-warning" role="alert">
          {error}
        </p>
      )}
      <iframe
        className="atlas-canvas"
        ref={host}
        title="Real SPHEREx infrared sky atlas"
        src="/atlas.html"
        onLoad={() =>
          host.current?.contentWindow?.postMessage(
            {
              type: 'atlas-config',
              channel,
              ra: target?.raDeg ?? 0,
              dec: target?.decDeg ?? 0,
              fov: Math.max(0.2, (target?.fovArcmin ?? 60) / 60),
            },
            location.origin,
          )
        }
      />
      <div className="atlas-footer">
        <p>
          The mosaic combines observations for sky navigation. The observation
          timeline retains individual dates. Click the sky to choose a new
          field.
        </p>
        {picked && (
          <button
            className="secondary-button"
            onClick={() =>
              onNavigate({
                raDeg: picked.ra,
                decDeg: picked.dec,
                fovArcmin: target?.fovArcmin ?? 10,
              })
            }
          >
            Load RA {picked.ra.toFixed(4)}°, Dec {picked.dec.toFixed(4)}°
          </button>
        )}
        <a
          href="https://caltech-ipac.github.io/irsa-tutorials/spherex-hipscube/"
          target="_blank"
          rel="noreferrer"
        >
          IRSA mosaic documentation
        </a>
      </div>
    </div>
  )
}
