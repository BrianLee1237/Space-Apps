import type { SearchTarget } from '../types/astronomy'

function sexagesimal(value: string, ra: boolean): number | null {
  const clean = value
    .trim()
    .replace(/[hHdD°mM′'sS″"]/g, ':')
    .replace(/\s+/g, ':')
    .replace(/:+$/, '')
  if (!clean) return null
  if (/^[-+]?\d+(?:\.\d+)?$/.test(clean)) {
    const deg = Number(clean)
    return Number.isFinite(deg) &&
      (ra ? deg >= 0 && deg < 360 : deg >= -90 && deg <= 90)
      ? deg
      : null
  }
  if (!clean.includes(':')) return null
  const parts = clean.split(':').filter(Boolean)
  if (
    parts.length < 2 ||
    parts.length > 3 ||
    parts.some((p) => !/^\d+(?:\.\d+)?$/.test(p.replace(/^[-+]/, '')))
  )
    return null
  const sign = parts[0].startsWith('-') ? -1 : 1
  const nums = parts.map((v) => Math.abs(Number(v)))
  if (
    nums.some((n) => !Number.isFinite(n)) ||
    nums[1] >= 60 ||
    (nums[2] ?? 0) >= 60
  )
    return null
  const result =
    sign * (nums[0] + nums[1] / 60 + (nums[2] ?? 0) / 3600) * (ra ? 15 : 1)
  return (ra ? result >= 0 && result < 360 : result >= -90 && result <= 90)
    ? result
    : null
}
export function parseSkyCoordinates(
  ra: string,
  dec: string,
  fov: number,
): SearchTarget | null {
  const raDeg = sexagesimal(ra, true),
    decDeg = sexagesimal(dec, false)
  if (raDeg === null || decDeg === null) return null
  return { raDeg, decDeg, fovArcmin: fov }
}
