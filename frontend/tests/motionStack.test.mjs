import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import {
  decodeMotionDataset, expectedOffsets, injectPractice, scanPractice, stackImages,
  timeFractions, ZERO,
} from '../src/features/motionStack.ts'

const metadata = JSON.parse(readFileSync(new URL('../public/motion-stack/comet.json', import.meta.url), 'utf8'))
const binary = readFileSync(new URL('../public/motion-stack/comet.bin', import.meta.url))
const bytes = Uint8Array.from(binary).buffer
const data = decodeMotionDataset(metadata, bytes)

function centralMean(image) {
  const center = Math.floor(data.size / 2)
  const pixels = []
  for (let y = center - 3; y <= center + 2; y++) {
    for (let x = center - 3; x <= center + 2; x++) pixels.push(image[y * data.size + x])
  }
  return pixels.reduce((sum, value) => sum + value, 0) / pixels.length
}

test('the predicted motion strengthens the real comet at the stack center', () => {
  const offsets = expectedOffsets(data)
  const reversed = offsets.map(([x, y]) => [-x, -y])
  const aligned = centralMean(stackImages(data.comet, data.size, offsets))
  const stationary = centralMean(stackImages(data.comet, data.size, offsets.map(() => ZERO)))
  const wrong = centralMean(stackImages(data.comet, data.size, reversed))
  assert.ok(aligned > stationary * 3)
  assert.ok(aligned > wrong * 3)
})

test('the blind scan recovers each injection and retains contrast on held-out frames', () => {
  const fractions = timeFractions(data.frames)
  for (const motion of [[-24, 16], [24, 16], [-24, -16], [24, -16],
    [-16, 24], [16, -24], [24, 24], [-24, -24]]) {
    const simulated = injectPractice(data, fractions, motion)
    const result = scanPractice(simulated, data.size, fractions)
    assert.equal(result.trials.length, 81)
    assert.deepEqual(result.best?.motion, motion)
    assert.ok(result.best.heldOut > 0)
  }
})

test('the decoder rejects a truncated scientific data asset', () => {
  assert.throws(() => decodeMotionDataset(metadata, bytes.slice(0, -2)), /incomplete/)
})
