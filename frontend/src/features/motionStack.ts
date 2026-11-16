export type Point = readonly [number, number]

export type Exposure = {
  id: string
  time: string
  wavelength: number
  sourceUrl: string
  position: Point
}

export type MotionMetadata = {
  size: number
  arcsecPerPixel: number
  practiceArcsecPerPixel: number
  pixelUnit: number
  frames: Exposure[]
}

export type MotionDataset = MotionMetadata & {
  comet: Float32Array[]
  practice: Float32Array[]
}

export const ZERO: Point = [0, 0]
export const PRACTICE_RANGE = 32
const STEPS = [-32, -24, -16, -8, 0, 8, 16, 24, 32]

export async function loadMotionDataset(signal: AbortSignal): Promise<MotionDataset> {
  const base = import.meta.env.BASE_URL + 'motion-stack/comet'
  const [metadata, pixels] = await Promise.all([
    fetch(base + '.json', { signal }),
    fetch(base + '.bin', { signal }),
  ])
  if (!metadata.ok || !pixels.ok) throw new Error('The comet images could not be loaded.')
  const info: MotionMetadata = await metadata.json()
  return decodeMotionDataset(info, await pixels.arrayBuffer())
}

export function decodeMotionDataset(info: MotionMetadata, bytes: ArrayBuffer) {
  const buffer = new DataView(bytes)
  const area = info.size ** 2
  const frameCount = info.frames.length
  if (buffer.byteLength !== area * frameCount * 4 || frameCount !== 4) {
    throw new Error('The downloaded comet images are incomplete.')
  }
  const planes = Array.from({ length: frameCount * 2 }, (_, frame) =>
    Float32Array.from({ length: area }, (_, index) => {
      const value = buffer.getInt16((frame * area + index) * 2, true)
      return value === -32768 ? NaN : value * info.pixelUnit
    }),
  )
  return { ...info, comet: planes.slice(0, frameCount), practice: planes.slice(frameCount) }
}

export function timeFractions(frames: Exposure[]) {
  const start = Date.parse(frames[0].time)
  const span = Date.parse(frames[frames.length - 1].time) - start
  return frames.map(frame => (Date.parse(frame.time) - start) / span - 0.5)
}

export function linearPath(fractions: number[], [dx, dy]: Point): Point[] {
  return fractions.map(time => [time * dx, time * dy])
}

function sample(image: Float32Array, size: number, x: number, y: number) {
  if (x < 0 || y < 0 || x > size - 1 || y > size - 1) return NaN
  const x0 = Math.floor(x), y0 = Math.floor(y)
  const fx = x - x0, fy = y - y0
  const top = y0 * size + x0
  const horizontal = (index: number) => fx === 0 ? image[index] : (
    (1 - fx) * image[index] + fx * image[index + 1]
  )
  return fy === 0 ? horizontal(top) : (1 - fy) * horizontal(top) + fy * horizontal(top + size)
}

export function stackImages(images: Float32Array[], size: number, offsets: Point[]) {
  const totals = new Float32Array(size * size)
  const counts = new Uint8Array(totals.length)
  images.forEach((image, index) => {
    const [dx, dy] = offsets[index]
    for (let y = 0; y < size; y++) {
      for (let x = 0; x < size; x++) {
        const value = sample(image, size, x + dx, y + dy)
        if (!Number.isFinite(value)) continue
        const pixel = y * size + x
        totals[pixel] += value
        counts[pixel]++
      }
    }
  })
  const minimum = Math.ceil(images.length / 2)
  return totals.map((total, index) => counts[index] >= minimum ? total / counts[index] : NaN)
}

export function displayLimits(images: Float32Array[]): Point {
  const values = images.flatMap(image => Array.from(image).filter(Number.isFinite)).sort((a, b) => a - b)
  if (!values.length) return [0, 1]
  const low = values[Math.floor(values.length * 0.15)]
  const high = values[Math.floor(values.length * 0.995)]
  return [low, Math.max(low + 0.001, high)]
}

export function expectedOffsets(data: MotionDataset): Point[] {
  const center = (data.size - 1) / 2
  return data.frames.map(({ position: [x, y] }) => [x - center, y - center])
}

export function injectPractice(data: MotionDataset, fractions: number[], motion: Point) {
  const size = data.size
  const center = (size - 1) / 2
  const sigma = 2.35
  const [dx, dy] = motion
  const [low, high] = displayLimits(data.practice)
  const amplitude = (high - low) * 0.20
  return data.practice.map((image, index) => {
    const x = center + dx * fractions[index]
    const y = center + dy * fractions[index]
    const result = image.slice()
    for (let row = Math.floor(y) - 9; row <= Math.ceil(y) + 9; row++) {
      for (let col = Math.floor(x) - 9; col <= Math.ceil(x) + 9; col++) {
        const distance = (row - y) ** 2 + (col - x) ** 2
        result[row * size + col] += amplitude * Math.exp(-distance / (2 * sigma ** 2))
      }
    }
    return result
  })
}

function apertureContrast(image: Float32Array, size: number, x: number, y: number) {
  let center = 0, background = 0, centerCount = 0, backgroundCount = 0
  for (let dy = -9; dy <= 9; dy++) {
    for (let dx = -9; dx <= 9; dx++) {
      const radiusSquared = dx * dx + dy * dy
      if (radiusSquared > 81 || (radiusSquared > 9 && radiusSquared < 36)) continue
      const value = sample(image, size, x + dx, y + dy)
      if (!Number.isFinite(value)) continue
      if (radiusSquared <= 9) {
        center += value
        centerCount++
      } else {
        background += value
        backgroundCount++
      }
    }
  }
  return centerCount >= 24 && backgroundCount >= 90 ? center / centerCount - background / backgroundCount : NaN
}

export function scanPractice(images: Float32Array[], size: number, fractions: number[]) {
  const center = (size - 1) / 2
  const trials = STEPS.flatMap(dy => STEPS.map(dx => {
    const motion: Point = [dx, dy]
    const offsets = linearPath(fractions, motion)
    const contrasts = images.map((image, index) =>
      apertureContrast(image, size, center + offsets[index][0], center + offsets[index][1]),
    )
    return { motion, score: (contrasts[0] + contrasts[2]) / 2, heldOut: (contrasts[1] + contrasts[3]) / 2 }
  }))
  const best = trials.filter(trial => Number.isFinite(trial.score)).reduce<typeof trials[number] | null>(
    (winner, trial) => !winner || trial.score > winner.score ? trial : winner,
    null,
  )
  return { trials, best }
}
