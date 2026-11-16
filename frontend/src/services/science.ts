import { request } from './api'
import type {
  AnalysisJob,
  EvidenceEntry,
  ScienceParameters,
  ScienceResult,
} from '../types/astronomy'

export async function runAnalysis(
  parameters: ScienceParameters,
  signal: AbortSignal,
  onProgress: (job: AnalysisJob) => void,
): Promise<ScienceResult> {
  const job = await request<AnalysisJob>('/science/jobs', signal, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(parameters),
  })
  const release = () => {
    void request(`/science/jobs/${job.id}/${job.subscription}`, undefined, {
      method: 'DELETE',
    }).catch(() => {})
  }
  signal.addEventListener('abort', release, { once: true })
  try {
    let current = job
    while (current.state === 'queued' || current.state === 'running') {
      onProgress(current)
      await new Promise<void>((resolve, reject) => {
        const abort = () => {
          clearTimeout(timer)
          reject(new DOMException('Cancelled', 'AbortError'))
        }
        const timer = setTimeout(() => {
          signal.removeEventListener('abort', abort)
          resolve()
        }, 600)
        if (signal.aborted) {
          abort()
          return
        }
        signal.addEventListener('abort', abort, { once: true })
      })
      current = await request<AnalysisJob>(`/science/jobs/${job.id}`, signal)
    }
    onProgress(current)
    if (current.state === 'cancelled')
      throw new DOMException('Cancelled', 'AbortError')
    if (current.state === 'failed' || !current.result)
      throw new Error(current.error || 'Analysis failed')
    return current.result
  } finally {
    signal.removeEventListener('abort', release)
    release()
  }
}

export function listEvidence() {
  return request<{ entries: EvidenceEntry[] }>('/science/evidence')
}
export function getEvidence(id:string){
  return request<EvidenceEntry>(`/science/evidence/${id}`)
}
export function saveEvidence(record: object) {
  return request<{ id: string }>('/science/evidence', undefined, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ record }),
  })
}
export function assessEvidence(
  id: string,
  reviewer: string,
  verdict: string,
  note: string,
) {
  return request(`/science/evidence/${id}/assessments`, undefined, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reviewer, verdict, note }),
  })
}
