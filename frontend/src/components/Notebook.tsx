import { useState } from 'react'
import {
  BookOpen,
  Download,
  Trash2,
  BookmarkPlus,
  FileDown,
} from 'lucide-react'
import type {
  Candidate,
  Observation,
  SavedFinding,
  SearchTarget,
} from '../types/astronomy'
import { downloadDiscoveryPdf } from '../utils/pdfReport'

function markdownReport(record: SavedFinding) {
  const lines = [
    '# SPHEREx observation note',
    '',
    `Saved: ${record.savedAt}`,
    '',
    `Position: RA ${record.target.raDeg}°, Dec ${record.target.decDeg}°`,
    `Field of view: ${record.target.fovArcmin} arcmin`,
    `Source: SPHEREx observations returned by project backend`,
    `Search link: ${location.origin}${location.pathname}?ra=${record.target.raDeg}&dec=${record.target.decDeg}&fov=${record.target.fovArcmin}`,
    '',
    '## Notes',
    record.note || 'No notes entered.',
    '',
  ]
  if (record.candidate)
    lines.push(
      '## Unverified candidate',
      `Candidate ID: ${record.candidate.id}`,
      `RA: ${record.candidate.raDeg}°`,
      `Dec: ${record.candidate.decDeg}°`,
      'Status: Unverified candidate; not a confirmed astronomical discovery.',
      '',
    )
  if (record.motionSummary)
    lines.push(
      '## Apparent displacement (not verified)',
      JSON.stringify(record.motionSummary),
      '',
    )
  lines.push(
    '## Evidence',
    ...record.observations.map(
      (o) =>
        `- ${o.id} | ${o.observedAt} | ${o.release || 'Release unspecified'}${o.flags?.length ? ` | Flags: ${o.flags.join(', ')}` : ''}`,
    ),
    '',
    'This file records observations and user notes. It is not scientific confirmation of a new object.',
  )
  if (record.analysis)
    lines.push(
      '## Reproducible analysis',
      '```json',
      JSON.stringify(record.analysis, null, 2),
      '```',
    )
  if (record.settings)
    lines.push('## Viewer settings', JSON.stringify(record.settings))
  return lines.join('\n')
}
function downloadMarkdown(record: SavedFinding) {
  const url = URL.createObjectURL(
    new Blob([markdownReport(record)], { type: 'text/markdown;charset=utf-8' }),
  )
  const link = document.createElement('a')
  link.href = url
  link.download = `spherex-note-${record.id.replace(/[^a-zA-Z0-9_-]/g, '')}.md`
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1500)
}
function downloadEvidence(record: SavedFinding) {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(record, null, 2)], { type: 'application/json' }),
  )
  const link = document.createElement('a')
  link.href = url
  link.download = `spherex-evidence-${record.id}.json`
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 2000)
}
export default function Notebook({
  items,
  target,
  frames,
  candidate,
  onSave,
  onDelete,
}: {
  items: SavedFinding[]
  target: SearchTarget | null
  frames: Observation[]
  candidate: Candidate | null
  onSave: (note: string) => void
  onDelete: (id: string) => void
}) {
  const [note, setNote] = useState('')
  const [exporting, setExporting] = useState('')
  const [error, setError] = useState('')
  async function exportPdf(item: SavedFinding) {
    setExporting(item.id)
    setError('')
    try {
      await downloadDiscoveryPdf(item)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unable to create PDF report.')
    } finally {
      setExporting('')
    }
  }
  return (
    <section className="inspector-body notebook-body">
      <p className="section-explainer">
        Notes are saved in this browser. PDF exports include archive dates, IDs,
        and available observation images.
      </p>
      {candidate && (
        <p className="control-hint">
          Saving with unverified candidate: {candidate.label || candidate.id}
        </p>
      )}
      <label className="field-label" htmlFor="notebook-note">
        Observation notes
      </label>
      <textarea
        id="notebook-note"
        className="note-input"
        value={note}
        maxLength={3000}
        onChange={(e) => setNote(e.target.value)}
        placeholder="What did you notice?"
        rows={4}
      />
      <button
        type="button"
        className="secondary-button full-button"
        disabled={!target || frames.length === 0}
        onClick={() => {
          onSave(note)
          setNote('')
        }}
      >
        <BookmarkPlus size={16} />
        Save current observation
      </button>
      {!target && (
        <small className="control-hint">
          Load observations before saving a note.
        </small>
      )}
      <div className="section-heading-row">
        <h3>
          <BookOpen size={16} /> Saved notes
        </h3>
        <span>{items.length}</span>
      </div>
      {items.length === 0 && <p className="empty-text">No saved notes.</p>}
      {error && (
        <p className="inline-warning" role="alert">
          {error}
        </p>
      )}
      {items.map((item) => (
        <article className="notebook-entry" key={item.id}>
          <div className="note-row">
            <strong>
              {item.candidate?.label ||
                item.target.name ||
                `RA ${item.target.raDeg.toFixed(4)}°`}
            </strong>
            <time>{new Date(item.savedAt).toLocaleDateString()}</time>
          </div>
          <p>{item.note || 'No notes entered.'}</p>
          <small>
            {item.observations.length} observation
            {item.observations.length === 1 ? '' : 's'} saved as references
          </small>
          <div className="entry-actions">
            <button
              type="button"
              disabled={!!exporting}
              onClick={() => void exportPdf(item)}
            >
              <FileDown size={14} />
              {exporting === item.id ? 'Exporting…' : 'Export PDF'}
            </button>
            <button type="button" onClick={() => downloadMarkdown(item)}>
              <Download size={14} />
              Markdown
            </button>
            <button type="button" onClick={() => downloadEvidence(item)}>
              Evidence JSON
            </button>
            <button
              type="button"
              onClick={() => onDelete(item.id)}
              aria-label="Remove note"
            >
              <Trash2 size={14} />
            </button>
          </div>
        </article>
      ))}
    </section>
  )
}
