import { useEffect, useRef, useState } from 'react'
import { ArrowUpRight, Crosshair, Move, RotateCcw, ZoomIn, ZoomOut } from 'lucide-react'

type Props = {
  selectedRa: number | null
  selectedDec: number | null
  fovArcmin: number
  loading: boolean
  onPick: (raDeg: number, decDeg: number) => void
  onSearch: () => void
}

type ShaderHandles = {
  program: WebGLProgram
  position: number
  matrix: WebGLUniformLocation
  rotation: WebGLUniformLocation
  color: WebGLUniformLocation
  kind: WebGLUniformLocation
  pointSize: WebGLUniformLocation
}
type DrawPart = { buffer: WebGLBuffer; count: number; primitive: number; color: [number, number, number, number]; kind: number; size: number }

const TAU = 2 * Math.PI
const DEG = Math.PI / 180
const radius = 1.23
const normalizeRa = (n: number) => ((n % 360) + 360) % 360
const clamp = (v: number, min: number, max: number) => Math.max(min, Math.min(max, v))
const toPoint = (raDeg: number, decDeg: number, r: number): [number, number, number] => {
  const ra = raDeg * DEG, dec = decDeg * DEG
  return [Math.cos(dec) * Math.cos(ra) * r, Math.sin(dec) * r, Math.cos(dec) * Math.sin(ra) * r]
}
const mul4 = (a: Float32Array, b: Float32Array) => {
  const out = new Float32Array(16)
  for (let col = 0; col < 4; col++) for (let row = 0; row < 4; row++)
    for (let k = 0; k < 4; k++) out[col * 4 + row] += a[k * 4 + row] * b[col * 4 + k]
  return out
}
const projection = (aspect: number) => {
  const f = 1 / Math.tan(40 * DEG / 2), near = 0.1, far = 32
  return new Float32Array([f / aspect, 0, 0, 0, 0, f, 0, 0, 0, 0, (far + near) / (near - far), -1, 0, 0, (2 * far * near) / (near - far), 0])
}
const matrix = (yaw: number, pitch: number, dist: number, aspect: number) => {
  const cy = Math.cos(yaw), sy = Math.sin(yaw), cx = Math.cos(pitch), sx = Math.sin(pitch)
  const ry = new Float32Array([cy, 0, -sy, 0, 0, 1, 0, 0, sy, 0, cy, 0, 0, 0, 0, 1])
  const rx = new Float32Array([1, 0, 0, 0, 0, cx, sx, 0, 0, -sx, cx, 0, 0, 0, 0, 1])
  const translate = new Float32Array([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, -dist, 1])
  const rot = mul4(rx, ry)
  return { mvp: mul4(projection(aspect), mul4(translate, rot)), rot: new Float32Array([rot[0], rot[1], rot[2], rot[4], rot[5], rot[6], rot[8], rot[9], rot[10]]) }
}
function sphereMesh(): number[] {
  const result: number[] = []
  const latSteps = 42, lonSteps = 80
  for (let i = 0; i < latSteps; i++) {
    const a = -90 + 180 * i / latSteps, b = -90 + 180 * (i + 1) / latSteps
    for (let j = 0; j < lonSteps; j++) {
      const l = 360 * j / lonSteps, r = 360 * (j + 1) / lonSteps
      result.push(...toPoint(l, a, radius), ...toPoint(r, a, radius), ...toPoint(l, b, radius))
      result.push(...toPoint(l, b, radius), ...toPoint(r, a, radius), ...toPoint(r, b, radius))
    }
  }
  return result
}
function makeGridLine(kind: 'lat' | 'lon', value: number, subdivisions = 160, r = radius + .007): number[] {
  const vertices: number[] = []
  for (let i = 0; i <= subdivisions; i++) {
    const t = i / subdivisions
    vertices.push(...(kind === 'lat' ? toPoint(t * 360, value, r) : toPoint(value, -90 + 180 * t, r)))
  }
  return vertices
}
function orbitRing(r: number, tilt: number, turn: number): number[] {
  const pts: number[] = []
  for (let i = 0; i <= 256; i++) {
    const a = TAU * i / 256
    const x = r * Math.cos(a), z = r * Math.sin(a)
    const yy = z * Math.sin(tilt), zz = z * Math.cos(tilt)
    pts.push(x * Math.cos(turn) + zz * Math.sin(turn), yy, -x * Math.sin(turn) + zz * Math.cos(turn))
  }
  return pts
}
function createShader(gl: WebGLRenderingContext, type: number, source: string) {
  const shader = gl.createShader(type)
  if (!shader) return null
  gl.shaderSource(shader, source)
  gl.compileShader(shader)
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) { gl.deleteShader(shader); return null }
  return shader
}
function buildProgram(gl: WebGLRenderingContext): ShaderHandles | null {
  const vertex = createShader(gl, gl.VERTEX_SHADER, `
    attribute vec3 aPosition;
    uniform mat4 uMatrix;
    uniform mat3 uRotation;
    uniform float uPointSize;
    varying vec3 vNormal;
    void main() {
      gl_Position = uMatrix * vec4(aPosition, 1.0);
      vNormal = normalize(uRotation * aPosition);
      gl_PointSize = uPointSize;
    }`)
  const fragment = createShader(gl, gl.FRAGMENT_SHADER, `
    precision mediump float;
    uniform vec4 uColor;
    uniform float uKind;
    varying vec3 vNormal;
    void main() {
      if (uKind < 0.5) {
        float diff = max(0.0, dot(normalize(vNormal), normalize(vec3(-0.2, 0.45, 1.0))));
        vec3 body = mix(vec3(0.025, 0.031, 0.035), vec3(0.091, 0.075, 0.051), diff * 0.86);
        gl_FragColor = vec4(body, 1.0);
      } else {
        if (uKind > 1.5 && distance(gl_PointCoord.xy, vec2(0.5)) > 0.49) discard;
        gl_FragColor = uColor;
      }
    }`)
  if (!vertex || !fragment) return null
  const program = gl.createProgram()
  if (!program) return null
  gl.attachShader(program, vertex); gl.attachShader(program, fragment); gl.linkProgram(program)
  gl.deleteShader(vertex); gl.deleteShader(fragment)
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) { gl.deleteProgram(program); return null }
  const matrixLoc = gl.getUniformLocation(program, 'uMatrix')
  const rotLoc = gl.getUniformLocation(program, 'uRotation')
  const colorLoc = gl.getUniformLocation(program, 'uColor')
  const kindLoc = gl.getUniformLocation(program, 'uKind')
  const sizeLoc = gl.getUniformLocation(program, 'uPointSize')
  if (!matrixLoc || !rotLoc || !colorLoc || !kindLoc || !sizeLoc) { gl.deleteProgram(program); return null }
  return { program, position: gl.getAttribLocation(program, 'aPosition'), matrix: matrixLoc, rotation: rotLoc, color: colorLoc, kind: kindLoc, pointSize: sizeLoc }
}

/** Geometric J2000 coordinate navigator: never renders fabricated observations. */
export default function CelestialNavigator({ selectedRa, selectedDec, fovArcmin, loading, onPick, onSearch }: Props) {
  const canvas = useRef<HTMLCanvasElement>(null)
  const picker = useRef(onPick)
  const selected = useRef({ ra: selectedRa, dec: selectedDec })
  const controls = useRef<{ rotate: (deltaYaw: number, deltaPitch: number) => void; zoom: (delta: number) => void; reset: () => void } | null>(null)
  const [error, setError] = useState(false)
  useEffect(() => { picker.current = onPick }, [onPick])
  useEffect(() => { selected.current = { ra: selectedRa, dec: selectedDec }; controls.current?.rotate(0, 0) }, [selectedRa, selectedDec])

  useEffect(() => {
    const element = canvas.current
    if (!element) return
    const gl = element.getContext('webgl', { antialias: true, alpha: true, preserveDrawingBuffer: false })
    if (!gl) { setError(true); return }
    const handles = buildProgram(gl)
    if (!handles) { setError(true); return }
    const parts: DrawPart[] = []
    const createPart = (points: number[], primitive: number, color: DrawPart['color'], kind = 1, size = 1) => {
      const buffer = gl.createBuffer()
      if (!buffer) return
      gl.bindBuffer(gl.ARRAY_BUFFER, buffer)
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(points), gl.STATIC_DRAW)
      parts.push({ buffer, count: points.length / 3, primitive, color, kind, size })
    }
    createPart(sphereMesh(), gl.TRIANGLES, [0.08, 0.07, 0.06, 1], 0)
    for (let dec = -75; dec <= 75; dec += 15) createPart(makeGridLine('lat', dec), gl.LINE_STRIP, dec === 0 ? [.89, .58, .26, .66] : [.72, .48, .28, .42])
    for (let ra = 0; ra < 360; ra += 15) createPart(makeGridLine('lon', ra), gl.LINE_STRIP, ra === 0 ? [.93, .68, .36, .72] : [.72, .48, .28, .39])
    createPart(orbitRing(1.48, .18, -.18), gl.LINE_STRIP, [.85, .56, .27, .52])
    createPart(orbitRing(1.66, -.44, .33), gl.LINE_STRIP, [.75, .49, .25, .24])
    createPart(orbitRing(1.78, 0.10, .06), gl.LINE_STRIP, [.72, .47, .26, .16])
    const nodes: number[] = []
    for (let dec = -60; dec <= 60; dec += 30) for (let ra = 0; ra < 360; ra += 30) nodes.push(...toPoint(ra, dec, radius + .014))
    createPart(nodes, gl.POINTS, [1, .71, .36, .9], 2, 3)
    const marker = gl.createBuffer()
    if (!marker) { setError(true); return }

    gl.enable(gl.DEPTH_TEST); gl.depthFunc(gl.LEQUAL); gl.enable(gl.BLEND)
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA)
    gl.useProgram(handles.program); gl.enableVertexAttribArray(handles.position)
    let yaw = 0.42, pitch = -0.24, distance = 4.45, disposed = false
    const render = () => {
      if (disposed) return
      const rect = element.getBoundingClientRect()
      if (!rect.width || !rect.height) return
      const dpr = Math.min(2, window.devicePixelRatio || 1)
      const w = Math.round(rect.width * dpr), h = Math.round(rect.height * dpr)
      if (element.width !== w || element.height !== h) { element.width = w; element.height = h }
      gl.viewport(0, 0, w, h)
      gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT)
      const matrices = matrix(yaw, pitch, distance, rect.width / rect.height)
      gl.uniformMatrix4fv(handles.matrix, false, matrices.mvp)
      gl.uniformMatrix3fv(handles.rotation, false, matrices.rot)
      const draw = (part: DrawPart) => {
        gl.bindBuffer(gl.ARRAY_BUFFER, part.buffer)
        gl.vertexAttribPointer(handles.position, 3, gl.FLOAT, false, 0, 0)
        gl.uniform4fv(handles.color, part.color)
        gl.uniform1f(handles.kind, part.kind)
        gl.uniform1f(handles.pointSize, part.size * dpr)
        gl.drawArrays(part.primitive, 0, part.count)
      }
      parts.forEach(draw)
      const { ra, dec } = selected.current
      if (ra !== null && dec !== null && Number.isFinite(ra) && Number.isFinite(dec)) {
        gl.bindBuffer(gl.ARRAY_BUFFER, marker)
        gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(toPoint(ra, dec, radius + .018)), gl.DYNAMIC_DRAW)
        const dot = (size: number, color: DrawPart['color']) => draw({ buffer: marker, count: 1, primitive: gl.POINTS, color, kind: 2, size })
        dot(21, [1, .69, .28, .23]); dot(10, [1, .72, .30, .96]); dot(3.6, [1, 1, .93, 1])
      }
    }
    const rotate = (deltaYaw: number, deltaPitch: number) => { yaw += deltaYaw; pitch = clamp(pitch + deltaPitch, -1.45, 1.45); render() }
    const zoom = (delta: number) => { distance = clamp(distance + delta, 3.0, 6.5); render() }
    controls.current = { rotate, zoom, reset: () => { yaw = 0.42; pitch = -0.24; distance = 4.45; render() } }
    const down = { x: 0, y: 0, lastX: 0, lastY: 0, dragging: false, moved: false, pointer: -1 }
    function pointerDown(e: PointerEvent) {
      if (e.button !== 0 && e.pointerType === 'mouse') return
      down.x = down.lastX = e.clientX; down.y = down.lastY = e.clientY
      down.dragging = true; down.moved = false; down.pointer = e.pointerId
      element!.setPointerCapture(e.pointerId)
    }
    function pointerMove(e: PointerEvent) {
      if (!down.dragging || e.pointerId !== down.pointer) return
      const dx = e.clientX - down.lastX, dy = e.clientY - down.lastY
      if (Math.hypot(e.clientX - down.x, e.clientY - down.y) > 6) down.moved = true
      if (down.moved) rotate(dx * .006, dy * .006)
      down.lastX = e.clientX; down.lastY = e.clientY
    }
    function pickCoordinates(clientX: number, clientY: number) {
      const box = element!.getBoundingClientRect()
      const nx = ((clientX - box.left) / box.width * 2 - 1) * (box.width / box.height) * Math.tan(20 * DEG)
      const ny = (1 - (clientY - box.top) / box.height * 2) * Math.tan(20 * DEG)
      const length = Math.hypot(nx, ny, 1), dx = nx / length, dy = ny / length, dz = -1 / length
      const b = 2 * distance * dz, c = distance * distance - radius * radius, disc = b * b - 4 * c
      if (disc < 0) return
      const t = (-b - Math.sqrt(disc)) / 2
      if (t <= 0) return
      const wx = t * dx, wy = t * dy, wz = distance + t * dz
      const cx = Math.cos(pitch), sx = Math.sin(pitch), cy = Math.cos(yaw), sy = Math.sin(yaw)
      const iy = wy * cx + wz * sx, iz = -wy * sx + wz * cx
      const lx = wx * cy - iz * sy, lz = wx * sy + iz * cy
      const raDeg = normalizeRa(Math.atan2(lz, lx) / DEG)
      const decDeg = clamp(Math.asin(clamp(iy / radius, -1, 1)) / DEG, -90, 90)
      picker.current(Number(raDeg.toFixed(6)), Number(decDeg.toFixed(6)))
    }
    function pointerUp(e: PointerEvent) {
      if (!down.dragging || e.pointerId !== down.pointer) return
      down.dragging = false
      if (element!.hasPointerCapture(e.pointerId)) element!.releasePointerCapture(e.pointerId)
      if (!down.moved) pickCoordinates(e.clientX, e.clientY)
    }
    const cancel = () => { down.dragging = false }
    const wheel = (event: WheelEvent) => { event.preventDefault(); zoom(Math.sign(event.deltaY) * .25) }
    const keydown = (e: KeyboardEvent) => {
      const movements: Record<string, [number, number]> = { ArrowLeft: [-.14, 0], ArrowRight: [.14, 0], ArrowUp: [0, -.14], ArrowDown: [0, .14] }
      if (e.key in movements) { e.preventDefault(); rotate(...movements[e.key]) }
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); const rect = element!.getBoundingClientRect(); pickCoordinates(rect.left + rect.width / 2, rect.top + rect.height / 2) }
    }
    element.addEventListener('pointerdown', pointerDown)
    element.addEventListener('pointermove', pointerMove)
    element.addEventListener('pointerup', pointerUp)
    element.addEventListener('pointercancel', cancel)
    element.addEventListener('wheel', wheel, { passive: false })
    element.addEventListener('keydown', keydown)
    const observer = new ResizeObserver(render); observer.observe(element)
    render()
    return () => {
      disposed = true; observer.disconnect(); controls.current = null
      element.removeEventListener('pointerdown', pointerDown)
      element.removeEventListener('pointermove', pointerMove)
      element.removeEventListener('pointerup', pointerUp)
      element.removeEventListener('pointercancel', cancel)
      element.removeEventListener('wheel', wheel)
      element.removeEventListener('keydown', keydown)
      parts.forEach(part => gl.deleteBuffer(part.buffer)); gl.deleteBuffer(marker); gl.deleteProgram(handles.program)
    }
  }, [])
  const hasSelection = selectedRa !== null && selectedDec !== null && Number.isFinite(selectedRa) && Number.isFinite(selectedDec)
  return <section className="celestial-navigator" aria-label="Interactive 3D celestial coordinate navigator">
    <div className="celestial-top-left"><span className="system-caption">CELESTIAL COORDINATES</span><small>RA 0°–360° <span className="nav-separator">/</span> DEC −90° to +90°</small></div>
    <div className="celestial-top-right"><span className="system-caption">J2000 REFERENCE GRID</span><small>Geometric navigation · no sky data</small></div>
    <div className="navigator-canvas-wrap">
      <div className="celestial-ornament" aria-hidden="true"><span className="orbital-ring orbital-ring-one"/><span className="orbital-ring orbital-ring-two"/><span className="orbital-axis"/></div>
      <canvas ref={canvas} className="celestial-canvas" tabIndex={0} aria-label="Rotate with drag or arrow keys. Click or press Enter to choose the visible coordinates on the sphere."/>
      {error && <p className="globe-unavailable">3D view unavailable. You can still enter coordinates in Controls.</p>}
    </div>
    <div className="celestial-controls" aria-label="Globe navigation controls">
      <button type="button" title="Zoom in" aria-label="Zoom globe in" onClick={() => controls.current?.zoom(-.35)}><ZoomIn size={17}/></button>
      <button type="button" title="Zoom out" aria-label="Zoom globe out" onClick={() => controls.current?.zoom(.35)}><ZoomOut size={17}/></button>
      <button type="button" title="Reset orientation" aria-label="Reset globe orientation" onClick={() => controls.current?.reset()}><RotateCcw size={16}/></button>
    </div>
    <div className="celestial-bottom-left"><div className="celestial-hint"><Move size={15}/>Drag to rotate <span>·</span> Click to select</div><div className="celestial-status"><span className="signal-dot"/> COORDINATE GRID ONLY — NOT AN OBSERVATION</div></div>
    <div className="celestial-bottom-right">
      {hasSelection ? <><span className="system-caption">SELECTED POSITION</span><strong>RA {selectedRa.toFixed(4)}° <span>/</span> DEC {selectedDec.toFixed(4)}°</strong><small>Field of view · {fovArcmin} arcmin</small></> : <><span className="system-caption">NO POSITION SELECTED</span><small>Select any visible point on the sphere</small></>}
      <button type="button" className="nav-load-button" onClick={onSearch} disabled={!hasSelection || loading}><Crosshair size={16}/>{loading ? 'Loading…' : 'Load SPHEREx data'}<ArrowUpRight size={15}/></button>
    </div>
  </section>
}
