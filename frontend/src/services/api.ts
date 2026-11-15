import type {
  BandSelection, CombineResponse, DiscoveryResponse, DifferenceResponse, Observation,
  ObservationsResponse, OverlayResponse, ResolvedTarget,
  SearchTarget, SpectrumRequest, SpectrumResponse,
} from '../types/astronomy'

/** Vite proxies /api to FastAPI on 127.0.0.1:8000. Production: set VITE_API_BASE_URL. */
const BASE = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/$/, '')
export class ApiError extends Error {
  status?: number
  constructor(message: string, status?: number) { super(message); this.status=status; this.name = 'ApiError' }
}
function params(input: Record<string, string|number|undefined>): string {
  const result = new URLSearchParams()
  for (const [key, value] of Object.entries(input)) if (value!==undefined) result.set(key, String(value))
  return result.toString()
}
async function request<T>(path: string, signal?: AbortSignal): Promise<T> {
  let response: Response
  try { response = await fetch(BASE + path, { signal, headers: { 'Accept': 'application/json' } }) }
  catch (e) {
    if ((e as Error)?.name === 'AbortError') throw e
    throw new ApiError('Unable to reach the data service. Check the FastAPI server.')
  }
  if (!response.ok) {
    if (response.status === 404 || response.status === 501) throw new ApiError('This backend endpoint is not available yet.', response.status)
    let detail = `Data service returned HTTP ${response.status}.`
    try {
      const body: unknown = await response.json()
      if (body && typeof body === 'object' && 'detail' in body && typeof body.detail === 'string') detail = body.detail
    } catch { /* Non-JSON error response. */ }
    throw new ApiError(detail, response.status)
  }
  try { return await response.json() as T }
  catch { throw new ApiError('Invalid JSON returned by the data service.') }
}

/** Accept backend-supplied image endpoints; never create image data. */
export function imageURL(value: string): string {
  if (/^https?:\/\//i.test(value)) return value
  if (value.startsWith('/')) {
    if (/^https?:\/\//i.test(BASE)) return new URL(value, BASE).href
    return value.startsWith('/api/') ? value : `${BASE}${value}`
  }
  return `${BASE}/${value.replace(/^\.\//,'')}`
}
export async function resolveTarget(name: string, signal?: AbortSignal) {
  const data = await request<ResolvedTarget>(`/resolve?${params({name})}`, signal)
  if (!Number.isFinite(data.raDeg) || !Number.isFinite(data.decDeg)) throw new ApiError('Target resolver returned invalid coordinates.')
  return data
}
export async function getObservations(target: SearchTarget, band: BandSelection, signal?: AbortSignal) {
  const data = await request<ObservationsResponse>(`/observations?${params({ra:target.raDeg,dec:target.decDeg,fov:target.fovArcmin,mode:band.mode,index:'index' in band?band.index:undefined})}`,signal)
  if (!data || !Array.isArray(data.observations)) throw new ApiError('Expected observations[] from the backend.')
  const observations = data.observations.filter((entry: Observation)=>
    typeof entry.id==='string' && typeof entry.imageUrl==='string' &&
    typeof entry.observedAt==='string' && Number.isFinite(Date.parse(entry.observedAt))
  ).sort((a,b)=>Date.parse(a.observedAt)-Date.parse(b.observedAt))
  return { ...data, observations }
}
export async function getCandidates(target: SearchTarget, observations: Observation[],signal?:AbortSignal) {
  const data=await request<DiscoveryResponse>(`/candidates?${params({ra:target.raDeg,dec:target.decDeg,fov:target.fovArcmin,ids:observations.map(o=>o.id).join(',')})}`,signal)
  if (!data || !Array.isArray(data.candidates)) throw new ApiError('Expected candidates[] from discovery service.')
  return { ...data, candidates:data.candidates.filter(c=>Number.isFinite(c.raDeg)&&Number.isFinite(c.decDeg)) }
}
export async function getSpectrum(req:SpectrumRequest,signal?:AbortSignal) {
  const data=await request<SpectrumResponse>(`/spectrum?${params({observationId:req.observationId,x:req.xFraction,y:req.yFraction,ra:req.raDeg,dec:req.decDeg})}`,signal)
  if (!data || !Array.isArray(data.samples) || typeof data.fluxUnit!=='string') throw new ApiError('Expected samples[] and fluxUnit from the spectrum service.')
  return {...data,samples:data.samples.filter(s=>Number.isFinite(s.wavelengthMicron)&&Number.isFinite(s.flux)).sort((a,b)=>a.wavelengthMicron-b.wavelengthMicron)}
}
export async function getDifference(fromId:string,toId:string,signal?:AbortSignal) {
  const data=await request<DifferenceResponse>(`/difference?${params({fromId,toId})}`,signal)
  if(!data || typeof data.imageUrl!=='string')throw new ApiError('Expected imageUrl from difference service.')
  return data
}
export async function getGaiaOverlay(observationId:string,signal?:AbortSignal) {
  const data=await request<OverlayResponse>(`/overlays?${params({observationId,catalog:'gaia-dr3'})}`,signal)
  if(!data || !Array.isArray(data.sources))throw new ApiError('Expected sources[] from Gaia overlay service.')
  return data
}
export async function getCombine(observationIds:string[],signal?:AbortSignal) {
  const data=await request<CombineResponse>(`/combine?${params({ids:observationIds.join(',')})}`,signal)
  if(!data || typeof data.imageUrl!=='string')throw new ApiError('Expected imageUrl from combine service.')
  return data
}
