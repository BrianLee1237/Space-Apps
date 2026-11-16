import { useState } from 'react'
import {
  AlertCircle,
  ArrowRightLeft,
  Crosshair,
  FileText,
  Layers,
  Radar,
  Sparkles,
} from 'lucide-react'
import type {
  Candidate,
  CombineResponse,
  DifferenceResponse,
  DiscoveryResponse,
  ImageLocation,
  Observation,
  SavedFinding,
  SearchTarget,
  SpectrumResponse,
  MatchResponse,
  MotionTrack,
  MatchedPair,
  ViewName,
} from '../types/astronomy'
import SpectrumPlot from './SpectrumPlot'
import Notebook from './Notebook'
import Guide from './Guide'

type Selection =
  | { type: 'image'; point: ImageLocation }
  | { type: 'candidate'; candidate: Candidate }
  | null
export default function Inspector({
  view,
  frame,
  frames,
  selection,
  spectrum,
  spectrumBusy,
  spectrumError,
  discovery,
  discoveryBusy,
  discoveryError,
  onScan,
  onCandidate,
  track,
  trackBusy,
  trackError,
  onTrack,
  diff,
  diffBusy,
  diffError,
  compareFrom,
  compareTo,
  onFrom,
  onTo,
  onGenerateDifference,
  onClearDifference,
  matches,
  matchBusy,
  matchError,
  onFindMatches,
  matchedPair,
  sliderActive,
  onToggleSlider,
  combine,
  combineBusy,
  combineError,
  onGenerateCombine,
  onClearCombine,
  target,
  notes,
  onSaveNote,
  onDeleteNote,
  onGuideTarget,
  guideBusy,
  activeGuide,
  onGoCompare,
  onGoDiscover,
  onGoMotion,
  onGoNotebook,
  onGoGuide,
  searchWarnings,
}: {
  view: ViewName
  frame: Observation | null
  frames: Observation[]
  selection: Selection
  spectrum: SpectrumResponse | null
  spectrumBusy: boolean
  spectrumError: string
  discovery: DiscoveryResponse | null
  discoveryBusy: boolean
  discoveryError: string
  onScan: () => void
  onCandidate: (c: Candidate) => void
  track: MotionTrack | null
  trackBusy: boolean
  trackError: string
  onTrack: () => void
  diff: DifferenceResponse | null
  diffBusy: boolean
  diffError: string
  compareFrom: number
  compareTo: number
  onFrom: (n: number) => void
  onTo: (n: number) => void
  onGenerateDifference: () => void
  onClearDifference: () => void
  matches: MatchResponse | null
  matchBusy: boolean
  matchError: string
  onFindMatches: () => void
  matchedPair: MatchedPair | null
  sliderActive: boolean
  onToggleSlider: () => void
  combine: CombineResponse | null
  combineBusy: boolean
  combineError: string
  onGenerateCombine: () => void
  onClearCombine: () => void
  target: SearchTarget | null
  notes: SavedFinding[]
  onSaveNote: (note: string) => void
  onDeleteNote: (id: string) => void
  onGuideTarget: (name: string) => void
  guideBusy: boolean
  activeGuide: string | null
  onGoCompare: () => void
  onGoDiscover: () => void
  onGoMotion: () => void
  onGoNotebook: () => void
  onGoGuide: () => void
  searchWarnings?: string[]
}) {
  const [explorerTab, setExplorerTab] = useState<'details' | 'metadata'>(
    'details',
  )
  const currentTitle =
    view === 'science'
      ? 'Science workspace'
      : view === 'explorer'
        ? 'Object details'
        : view === 'motion'
          ? 'Motion tracking'
          : view === 'discover'
            ? 'Discovery mode'
            : view === 'spectrum'
              ? 'Spectral fingerprint'
              : view === 'compare'
                ? 'Compare observations'
                : view === 'notebook'
                  ? 'Discovery notebook'
                  : 'Guided exploration'
  const candidate = selection?.type === 'candidate' ? selection.candidate : null
  return (
    <aside className="inspector" aria-label={currentTitle}>
      <div className="inspector-header">
        {view === 'explorer' ? (
          <div className="inspector-tabs">
            <button
              className={explorerTab === 'details' ? 'active' : ''}
              type="button"
              onClick={() => setExplorerTab('details')}
            >
              Object details
            </button>
            <button
              type="button"
              className={explorerTab === 'metadata' ? 'active' : ''}
              onClick={() => setExplorerTab('metadata')}
            >
              Metadata
            </button>
          </div>
        ) : (
          <h2>{currentTitle}</h2>
        )}
      </div>
      {!frames.length &&
        ['motion', 'discover', 'spectrum', 'compare'].includes(view) && (
          <section className="inspector-body" aria-label="Load dated observations">
            <strong>Dated observations required</strong>
            <p className="section-explainer">
              Choose a saved observation field above or open a challenge target
              in Guide to use this tool. Motion, candidate highlighting and
              comparison require at least two exposures.
            </p>
            <button
              className="secondary-button full-button"
              type="button"
              onClick={onGoGuide}
            >
              Open guided targets
            </button>
          </section>
        )}
      {candidate && (
        <section className="change-explanation" aria-live="polite">
          <strong>
            {candidate.label} ·{' '}
            {candidate.classification === 'moving-source'
              ? 'Possible motion'
              : 'Possible brightness change'}
          </strong>
          <p>{candidate.caption || candidate.notes}</p>
          {candidate.earlierAt && (
            <small>
              {new Date(candidate.earlierAt).toLocaleDateString()} →{' '}
              {new Date(candidate.laterAt!).toLocaleDateString()} ·{' '}
              {candidate.elapsedDays?.toFixed(1)} days
            </small>
          )}
        </section>
      )}
      {view === 'science' && (
        <section className="science-shortcuts">
          {frames.length ? (
            <>
              <strong>Explore the selected source</strong>
              <p>
                Light curves use native aperture photometry and variance-derived
                errors. Image processing compares compatible wavelength
                channels.
              </p>
              <p>
                Select a source in Explorer, then open Science. The atlas
                provides real infrared sky navigation. Evidence can be saved,
                downloaded, and reviewed locally.
              </p>
              <a
                href="https://irsa.ipac.caltech.edu/onlinehelp/spherex/spherex/sp.html"
                target="_blank"
                rel="noreferrer"
              >
                IRSA forced-photometry documentation
              </a>
            </>
          ) : (
            <p>
              Explore real SPHEREx imagery in 102 infrared channels. The all-sky
              mosaic combines observation dates. Open a saved observation field
              to compare epochs and highlight candidate changes.
            </p>
          )}
        </section>
      )}
      {view === 'guide' && (
        <Guide
          onSelect={onGuideTarget}
          loading={guideBusy}
          active={activeGuide}
          frames={frames}
          pair={matchedPair}
          onCompare={onGoCompare}
          onDiscover={onGoDiscover}
          onMotion={onGoMotion}
          onNotebook={onGoNotebook}
        />
      )}
      {view === 'notebook' && (
        <Notebook
          items={notes}
          target={target}
          frames={frames}
          candidate={candidate}
          onSave={onSaveNote}
          onDelete={onDeleteNote}
        />
      )}
      {view === 'motion' && (
        <section className="inspector-body motion-body">
          <p className="section-explainer">
            Choose a visible source in Observations, then measure its position
            in compatible epochs. These are unverified image centroids.
          </p>
          <button
            className="secondary-button full-button"
            type="button"
            disabled={
              !selection ||
              selection.type !== 'image' ||
              frames.length < 2 ||
              trackBusy
            }
            onClick={onTrack}
          >
            {trackBusy ? 'Measuring positions…' : 'Track selected source'}
          </button>
          {selection?.type === 'image' && (
            <p className="control-hint">
              Selected image position:{' '}
              {Math.round(selection.point.xFraction * 100)}%,{' '}
              {Math.round(selection.point.yFraction * 100)}%
            </p>
          )}
          {(!selection || selection.type !== 'image') && (
            <p className="control-hint">
              Select a source in Explorer. The sphere cannot be used to track a
              detected source.
            </p>
          )}
          {trackError && (
            <p className="inline-warning" role="alert">
              {trackError}
            </p>
          )}
          {track && (
            <div className="motion-results" role="status">
              <strong>
                {track.summary
                  ? `${track.summary.apparentShiftArcsec.toFixed(2)} arcsec apparent shift`
                  : 'No reliable track measured'}
              </strong>
              {track.fit && (
                <div className="motion-summary">
                  <strong>Weighted linear fit</strong>
                  <p>
                    East {track.fit.eastArcsecPerYear.toFixed(2)} ±{' '}
                    {track.fit.rateUncertaintyArcsecPerYear.toFixed(2)}{' '}
                    arcsec/year
                  </p>
                  <p>
                    North {track.fit.northArcsecPerYear.toFixed(2)} ±{' '}
                    {track.fit.rateUncertaintyArcsecPerYear.toFixed(2)}{' '}
                    arcsec/year
                  </p>
                  <small>
                    Assumed {track.fit.assumedAstrometricFloorArcsec}-arcsec
                    astrometric floor. Validate with reference stars.
                  </small>
                </div>
              )}
              {track.summary && (
                <>
                  <p>
                    {track.summary.observationsMeasured} dated measurements over{' '}
                    {track.summary.baselineDays.toFixed(1)} days
                  </p>
                  <p>
                    Approximate rate:{' '}
                    {track.summary.apparentRateArcsecPerYear?.toFixed(2) ??
                      'Unavailable'}{' '}
                    arcsec/year
                  </p>
                </>
              )}
              <ol className="motion-measurements">
                {track.measurements.map((point) => (
                  <li key={point.observationId}>
                    <time>
                      {new Date(point.observedAt).toLocaleDateString()}
                    </time>
                    <span>RA {point.raDeg.toFixed(6)}°</span>
                    <span>Dec {point.decDeg.toFixed(6)}°</span>
                    <small>SNR {point.peakSnr.toFixed(1)}</small>
                  </li>
                ))}
              </ol>
              <details className="processing-notes">
                <summary>Method and limitations</summary>
                <p>{track.method}</p>
                {track.warnings.map((w, i) => (
                  <p key={i}>{w}</p>
                ))}
              </details>
            </div>
          )}
        </section>
      )}
      {view === 'compare' && (
        <section className="inspector-body">
          <p className="section-explainer">
            Only compare images at similar wavelengths. Matching checks real
            FITS metadata.
          </p>
          <button
            className="secondary-button full-button"
            type="button"
            disabled={frames.length < 2 || matchBusy}
            onClick={onFindMatches}
          >
            {matchBusy ? 'Checking wavelengths…' : 'Find comparable epochs'}
          </button>
          {matchError && (
            <p className="inline-warning" role="alert">
              {matchError}
            </p>
          )}
          {matches && (
            <div className="match-summary" role="status">
              <strong>
                {matches.pairs.length
                  ? `${matches.pairs.length} compatible pairs found`
                  : 'No matched pairs found'}
              </strong>
              {matchedPair && (
                <p>
                  Selected: {matchedPair.elapsedDays.toFixed(1)} days apart ·
                  detector {matchedPair.detector} ·{' '}
                  {matchedPair.wavelengthDifferencePercent.toFixed(2)}%
                  wavelength difference
                  {matchedPair.hasQualityFlags ? ' · flagged' : ''}
                </p>
              )}
              {matches.warnings.map((w, i) => (
                <p key={i} className="control-hint">
                  {w}
                </p>
              ))}
            </div>
          )}
          <label className="field-label" htmlFor="compare-one">
            Earlier observation
          </label>
          <select
            className="inspector-select"
            id="compare-one"
            value={compareFrom}
            disabled={frames.length < 2}
            onChange={(e) => onFrom(Number(e.target.value))}
          >
            {frames.length === 0 && <option value={0}>No data</option>}
            {frames.map((o, i) => (
              <option value={i} key={o.id}>
                {new Date(o.observedAt).toLocaleString()}
              </option>
            ))}
          </select>
          <label className="field-label" htmlFor="compare-two">
            Later observation
          </label>
          <select
            className="inspector-select"
            id="compare-two"
            value={compareTo}
            disabled={frames.length < 2}
            onChange={(e) => onTo(Number(e.target.value))}
          >
            {frames.length === 0 && <option value={0}>No data</option>}
            {frames.map((o, i) => (
              <option value={i} key={o.id}>
                {new Date(o.observedAt).toLocaleString()}
              </option>
            ))}
          </select>
          <button
            className="secondary-button full-button"
            type="button"
            disabled={!matchedPair || compareFrom === compareTo}
            onClick={onToggleSlider}
          >
            <ArrowRightLeft size={16} />
            {sliderActive
              ? 'Close before/after slider'
              : 'Open before/after slider'}
          </button>
          <button
            className="secondary-button full-button"
            type="button"
            disabled={!matchedPair || compareFrom === compareTo || diffBusy}
            onClick={onGenerateDifference}
          >
            <ArrowRightLeft size={16} />
            {diffBusy ? 'Processing…' : 'Generate difference image'}
          </button>
          {diff && (
            <div className="result-inline" role="status">
              <strong>Difference image ready</strong>
              <button type="button" onClick={onClearDifference}>
                View original
              </button>
              <details className="processing-notes">
                <summary>
                  Processing details
                  {diff.warnings?.length
                    ? ` (${diff.warnings.length} notes)`
                    : ''}
                </summary>
                <p>{diff.method || 'Processing method not supplied.'}</p>
                {diff.warnings?.map((s, i) => (
                  <p className="quality-warning" key={i}>
                    <AlertCircle size={14} />
                    {s}
                  </p>
                ))}
              </details>
            </div>
          )}
          {diffError && (
            <p className="inline-warning" role="alert">
              {diffError}
            </p>
          )}
          {frames.length < 2 && (
            <p className="empty-text">Requires two or more observations.</p>
          )}
          {frames.length >= 2 && !matchedPair && (
            <p className="control-hint">
              The before/after slider requires a confirmed wavelength match.
              Difference images remain quick-look and must be interpreted with
              their warnings.
            </p>
          )}
        </section>
      )}
      {view === 'discover' && (
        <section className="inspector-body">
          <p className="section-explainer">
            Look for movement or brightness changes between observations.
            Results are unverified.
          </p>
          <button
            className="secondary-button full-button"
            type="button"
            onClick={onScan}
            disabled={frames.length < 2 || discoveryBusy}
          >
            <Radar size={16} />
            {discoveryBusy ? 'Highlighting…' : 'Highlight candidate changes'}
          </button>
          {frames.length < 2 && (
            <p className="empty-text">
              Load at least two observations to compare.
            </p>
          )}
          {discoveryError && (
            <p className="inline-warning" role="alert">
              {discoveryError}
            </p>
          )}
          {discovery && (
            <>
              <div className="section-heading-row">
                <h3>Candidate detections</h3>
                <span>{discovery.candidates.length}</span>
              </div>
              {discovery.method && (
                <p className="control-hint">Method: {discovery.method}</p>
              )}
              {discovery.candidates.length === 0 && (
                <p className="empty-text">No candidates returned.</p>
              )}
              {discovery.candidates.map((c) => (
                <button
                  type="button"
                  className="candidate-row"
                  key={c.id}
                  onClick={() => onCandidate(c)}
                >
                  <span className="candidate-icon">
                    <Crosshair size={16} />
                  </span>
                  <span>
                    <strong>{c.label || `Candidate ${c.id}`}</strong>
                    <small>
                      RA {c.raDeg.toFixed(5)}°, Dec {c.decDeg.toFixed(5)}°
                    </small>
                    {c.classification && (
                      <small>{c.classification} · Unverified</small>
                    )}
                    {c.caption && (
                      <small className="candidate-description">
                        {c.caption}
                      </small>
                    )}
                    {c.catalogMatches?.map((row) => (
                      <small key={row.id}>
                        Near {row.label ?? row.id} ·{' '}
                        {row.separationArcsec.toFixed(1)} arcsec
                      </small>
                    ))}
                  </span>
                </button>
              ))}
              {discovery.warnings?.map((s, i) => (
                <p className="quality-warning" key={i}>
                  <AlertCircle size={14} />
                  {s}
                </p>
              ))}
            </>
          )}
        </section>
      )}
      {view === 'spectrum' && (
        <section className="inspector-body">
          <p className="section-explainer">
            Select a source to view its measured infrared spectrum.
          </p>
          <div className="panel-section-title">
            <Sparkles size={15} />
            Measurements
          </div>
          {spectrumBusy ? (
            <p className="empty-text">Loading spectrum…</p>
          ) : spectrum ? (
            <>
              <SpectrumPlot data={spectrum} />
              <div className="spectrum-summary">
                <strong>{spectrum.samples.length} measured points</strong>
                <small>Flux unit: {spectrum.fluxUnit}</small>
                {spectrum.extractionMethod && (
                  <small>Method: {spectrum.extractionMethod}</small>
                )}
              </div>
              {spectrum.warnings?.map((w, i) => (
                <p className="quality-warning" key={i}>
                  <AlertCircle size={14} />
                  {w}
                </p>
              ))}
            </>
          ) : (
            <p className="empty-text">No spectrum available.</p>
          )}
          {spectrumError && (
            <p className="inline-warning" role="alert">
              {spectrumError}
            </p>
          )}
        </section>
      )}
      {view === 'explorer' && explorerTab === 'metadata' && (
        <section className="inspector-body">
          <div className="panel-section-title">
            <FileText size={15} />
            Observation metadata
          </div>
          {!frame ? (
            <p className="empty-text">No metadata available.</p>
          ) : (
            <dl className="metadata-list">
              <div>
                <dt>Observation ID</dt>
                <dd>{frame.id}</dd>
              </div>
              <div>
                <dt>Observed</dt>
                <dd>{new Date(frame.observedAt).toLocaleString()}</dd>
              </div>
              {frame.release && (
                <div>
                  <dt>Release</dt>
                  <dd>{frame.release}</dd>
                </div>
              )}
              {frame.detector && (
                <div>
                  <dt>Detector</dt>
                  <dd>{frame.detector}</dd>
                </div>
              )}
              {frame.channel && (
                <div>
                  <dt>Channel</dt>
                  <dd>{frame.channel}</dd>
                </div>
              )}
              {frame.centralWavelengthMicron != null && (
                <div>
                  <dt>Center wavelength</dt>
                  <dd>{frame.centralWavelengthMicron.toFixed(4)} µm</dd>
                </div>
              )}
              {frame.bandwidthMicron != null && (
                <div>
                  <dt>Bandwidth</dt>
                  <dd>{frame.bandwidthMicron.toFixed(4)} µm</dd>
                </div>
              )}
              {frame.psfFwhmArcsec != null && (
                <div>
                  <dt>PSF FWHM</dt>
                  <dd>{frame.psfFwhmArcsec.toFixed(2)} arcsec</dd>
                </div>
              )}
              {frame.exposureSeconds !== undefined && (
                <div>
                  <dt>Exposure</dt>
                  <dd>{frame.exposureSeconds} seconds</dd>
                </div>
              )}
              {frame.flags?.length ? (
                <div>
                  <dt>Quality flags</dt>
                  <dd>{frame.flags.join(', ')}</dd>
                </div>
              ) : null}
            </dl>
          )}
          <p className="control-hint">
            Metadata from the selected observation.
          </p>
          {searchWarnings?.map((s, i) => (
            <p className="quality-warning" key={i}>
              <AlertCircle size={14} />
              {s}
            </p>
          ))}
        </section>
      )}
      {view === 'explorer' && explorerTab === 'details' && (
        <section className="inspector-body">
          <div className="panel-section-title">
            <Crosshair size={15} />
            Selection
          </div>
          {!selection ? (
            <div className="empty-state">
              <strong>No selection</strong>
              <span>
                {frame
                  ? 'Click the image to inspect a position.'
                  : 'Load an observation to inspect an image.'}
              </span>
            </div>
          ) : (
            <div className="quiet-panel">
              <strong>
                {candidate?.label ||
                  (candidate ? 'Unverified candidate' : 'Image selection')}
              </strong>
              {candidate ? (
                <>
                  <span>RA {candidate.raDeg.toFixed(6)}°</span>
                  <span>Dec {candidate.decDeg.toFixed(6)}°</span>
                  <span>Unverified candidate</span>
                </>
              ) : (
                <span>
                  Image point{' '}
                  {Math.round(
                    (selection.type === 'image'
                      ? selection.point.xFraction
                      : 0) * 100,
                  )}
                  %,{' '}
                  {Math.round(
                    (selection.type === 'image'
                      ? selection.point.yFraction
                      : 0) * 100,
                  )}
                  %
                </span>
              )}
            </div>
          )}
          <div className="panel-divider" />
          <div className="panel-section-title">
            <Layers size={15} />
            Combine exposures
          </div>
          {frames.length >= 2 ? (
            <>
              <p className="control-hint">
                Inverse-variance stack of compatible wavelength-channel
                exposures. Moving sources may blur.
              </p>
              <button
                className="secondary-button full-button"
                type="button"
                disabled={combineBusy}
                onClick={onGenerateCombine}
              >
                <Layers size={16} />
                {combineBusy ? 'Combining…' : 'Stack compatible exposures'}
              </button>
            </>
          ) : (
            <p className="empty-text">
              Available with two or more observations.
            </p>
          )}
          {combine && (
            <div className="result-inline" role="status">
              <strong>Combined image ready</strong>
              <button type="button" onClick={onClearCombine}>
                View original
              </button>
              <details className="processing-notes">
                <summary>
                  Processing details
                  {combine.warnings?.length
                    ? ` (${combine.warnings.length} notes)`
                    : ''}
                </summary>
                <p>
                  {combine.frameCount} contributing exposures.{' '}
                  {combine.method || 'Processing method not supplied.'}
                </p>
                {combine.warnings?.map((s, i) => (
                  <p className="quality-warning" key={i}>
                    <AlertCircle size={14} />
                    {s}
                  </p>
                ))}
              </details>
            </div>
          )}
          {combineError && (
            <p className="inline-warning" role="alert">
              {combineError}
            </p>
          )}
          <div className="panel-divider" />
          <div className="panel-section-title">
            <Sparkles size={15} />
            Spectral fingerprint
          </div>
          {spectrumBusy ? (
            <p className="empty-text">Loading spectrum…</p>
          ) : spectrum ? (
            <>
              <SpectrumPlot data={spectrum} />
              <small className="control-hint">
                {spectrum.samples.length} measured point
                {spectrum.samples.length === 1 ? '' : 's'} · {spectrum.fluxUnit}
              </small>
              {spectrum.warnings?.some((w) => w.includes('locally cached')) && (
                <p className="control-hint">
                  Partial wavelength coverage from cached observations.
                </p>
              )}
            </>
          ) : (
            <div className="empty-state">
              <strong>No spectrum yet</strong>
              <span>Select a source to view its spectrum.</span>
            </div>
          )}
          {spectrumError && (
            <p className="inline-warning" role="alert">
              {spectrumError}
            </p>
          )}
          <div className="panel-divider" />
          <div className="panel-section-title">
            <Radar size={15} />
            Discovery candidates
          </div>
          {discovery?.candidates.length ? (
            <>
              <p className="control-hint">
                {discovery.candidates.length} unverified candidates
              </p>
              {discovery.candidates.slice(0, 5).map((c) => (
                <button
                  key={c.id}
                  type="button"
                  className="compact-candidate"
                  onClick={() => onCandidate(c)}
                >
                  {c.label || c.id}
                  <span>Inspect</span>
                </button>
              ))}
            </>
          ) : (
            <div className="empty-state">
              <strong>No candidates yet</strong>
              <span>Open Discover to check for changes.</span>
            </div>
          )}
          {frame?.flags?.length ? (
            <p className="quality-warning">
              <AlertCircle size={14} />
              {frame.flags.join(', ')}
            </p>
          ) : null}
        </section>
      )}
    </aside>
  )
}
