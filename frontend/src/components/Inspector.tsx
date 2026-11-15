import { useState } from 'react'
import { AlertCircle, ArrowRightLeft, Crosshair, FileText, Layers, Radar, Sparkles } from 'lucide-react'
import type { Candidate, CombineResponse, DifferenceResponse, DiscoveryResponse, ImageLocation, Observation,
  SavedFinding, SearchTarget, SpectrumResponse, ViewName } from '../types/astronomy'
import SpectrumPlot from './SpectrumPlot'
import Notebook from './Notebook'
import Guide from './Guide'

type Selection={type:'image';point:ImageLocation}|{type:'candidate';candidate:Candidate}|null
export default function Inspector({view,frame,frames,selection,spectrum,spectrumBusy,spectrumError,
  discovery,discoveryBusy,discoveryError,onScan,onCandidate,
  diff,diffBusy,diffError,compareFrom,compareTo,onFrom,onTo,onGenerateDifference,onClearDifference,
  combine,combineBusy,combineError,onGenerateCombine,onClearCombine,
  target,notes,onSaveNote,onDeleteNote,onGuideTarget,guideBusy,searchWarnings}:{
    view:ViewName;frame:Observation|null;frames:Observation[];selection:Selection;
    spectrum:SpectrumResponse|null;spectrumBusy:boolean;spectrumError:string;
    discovery:DiscoveryResponse|null;discoveryBusy:boolean;discoveryError:string;onScan:()=>void;onCandidate:(c:Candidate)=>void;
    diff:DifferenceResponse|null;diffBusy:boolean;diffError:string;compareFrom:number;compareTo:number;onFrom:(n:number)=>void;onTo:(n:number)=>void;onGenerateDifference:()=>void;onClearDifference:()=>void;
    combine:CombineResponse|null;combineBusy:boolean;combineError:string;onGenerateCombine:()=>void;onClearCombine:()=>void;
    target:SearchTarget|null;notes:SavedFinding[];onSaveNote:(note:string)=>void;onDeleteNote:(id:string)=>void;onGuideTarget:(name:string)=>void;guideBusy:boolean;searchWarnings?:string[];
  }) {
  const [explorerTab,setExplorerTab]=useState<'details'|'metadata'>('details')
  const currentTitle=view==='explorer'?'Object details':view==='discover'?'Discovery mode':view==='spectrum'?'Spectral fingerprint':view==='compare'?'Compare observations':view==='notebook'?'Discovery notebook':'Guided exploration'
  const candidate=selection?.type==='candidate'?selection.candidate:null
  return <aside className="inspector" aria-label={currentTitle}>
    <div className="inspector-header">
      {view==='explorer'?<div className="inspector-tabs"><button className={explorerTab==='details'?'active':''} type="button" onClick={()=>setExplorerTab('details')}>Object details</button><button type="button" className={explorerTab==='metadata'?'active':''} onClick={()=>setExplorerTab('metadata')}>Metadata</button></div>:<h2>{currentTitle}</h2>}
    </div>
    {view==='guide'&&<Guide onSelect={onGuideTarget} loading={guideBusy}/>}
    {view==='notebook'&&<Notebook items={notes} target={target} frames={frames} candidate={candidate} onSave={onSaveNote} onDelete={onDeleteNote}/>}
    {view==='compare'&&<section className="inspector-body">
      <p className="section-explainer">Compare real observations of the same sky region. The backend must align images before subtraction.</p>
      <label className="field-label" htmlFor="compare-one">Earlier observation</label><select className="inspector-select" id="compare-one" value={compareFrom} disabled={frames.length<2} onChange={e=>onFrom(Number(e.target.value))}>
        {frames.length===0&&<option value={0}>No data</option>}{frames.map((o,i)=><option value={i} key={o.id}>{new Date(o.observedAt).toLocaleString()}</option>)}
      </select>
      <label className="field-label" htmlFor="compare-two">Later observation</label><select className="inspector-select" id="compare-two" value={compareTo} disabled={frames.length<2} onChange={e=>onTo(Number(e.target.value))}>
        {frames.length===0&&<option value={0}>No data</option>}{frames.map((o,i)=><option value={i} key={o.id}>{new Date(o.observedAt).toLocaleString()}</option>)}
      </select>
      <button className="secondary-button full-button" type="button" disabled={frames.length<2||compareFrom===compareTo||diffBusy} onClick={onGenerateDifference}><ArrowRightLeft size={16}/>{diffBusy?'Processing…':'Generate difference image'}</button>
      {diff&&<div className="result-inline"><strong>Difference image loaded</strong><p>{diff.method||'Backend processing method not supplied.'}</p><button type="button" onClick={onClearDifference}>Return to original image</button></div>}
      {diffError&&<p className="inline-warning" role="alert">{diffError}</p>}{diff?.warnings?.map((s,i)=><p className="quality-warning" key={i}><AlertCircle size={14}/>{s}</p>)}
      {frames.length<2&&<p className="empty-text">At least two real observations are required.</p>}
    </section>}
    {view==='discover'&&<section className="inspector-body">
      <p className="section-explainer">Flag possible moving or variable sources across real SPHEREx observation epochs. These are not confirmed discoveries.</p>
      <button className="secondary-button full-button" type="button" onClick={onScan} disabled={frames.length<2||discoveryBusy}><Radar size={16}/>{discoveryBusy?'Scanning…':'Find candidate changes'}</button>
      {frames.length<2&&<p className="empty-text">Load at least two observations to run a comparison.</p>}
      {discoveryError&&<p className="inline-warning" role="alert">{discoveryError}</p>}
      {discovery&&<><div className="section-heading-row"><h3>Candidate detections</h3><span>{discovery.candidates.length}</span></div>
        {discovery.method&&<p className="control-hint">Method: {discovery.method}</p>}
        {discovery.candidates.length===0&&<p className="empty-text">No candidates returned.</p>}
        {discovery.candidates.map(c=><button type="button" className="candidate-row" key={c.id} onClick={()=>onCandidate(c)}>
          <span className="candidate-icon"><Crosshair size={16}/></span><span><strong>{c.label||`Candidate ${c.id}`}</strong><small>RA {c.raDeg.toFixed(5)}°, Dec {c.decDeg.toFixed(5)}°</small>{c.classification&&<small>{c.classification} · Unverified</small>}</span>
        </button>)}
        {discovery.warnings?.map((s,i)=><p className="quality-warning" key={i}><AlertCircle size={14}/>{s}</p>)}
      </>}
    </section>}
    {view==='spectrum'&&<section className="inspector-body">
      <p className="section-explainer">Click a source in an observation or select a discovery candidate to request measured near-infrared flux.</p>
      <div className="panel-section-title"><Sparkles size={15}/>Spectral measurements</div>
      {spectrumBusy?<p className="empty-text">Loading spectrum…</p>:spectrum?<><SpectrumPlot data={spectrum}/><div className="spectrum-summary"><strong>{spectrum.samples.length} measured points</strong><small>Flux unit: {spectrum.fluxUnit}</small>{spectrum.extractionMethod&&<small>Method: {spectrum.extractionMethod}</small>}</div>{spectrum.warnings?.map((w,i)=><p className="quality-warning" key={i}><AlertCircle size={14}/>{w}</p>)}</>:<p className="empty-text">No spectrum available.</p>}
      {spectrumError&&<p className="inline-warning" role="alert">{spectrumError}</p>}
    </section>}
    {view==='explorer'&&explorerTab==='metadata'&&<section className="inspector-body">
      <div className="panel-section-title"><FileText size={15}/>Observation metadata</div>
      {!frame?<p className="empty-text">No metadata available.</p>:<dl className="metadata-list">
        <div><dt>Observation ID</dt><dd>{frame.id}</dd></div><div><dt>Observed</dt><dd>{new Date(frame.observedAt).toLocaleString()}</dd></div>
        {frame.release&&<div><dt>Release</dt><dd>{frame.release}</dd></div>}
        {frame.detector&&<div><dt>Detector</dt><dd>{frame.detector}</dd></div>}
        {frame.channel&&<div><dt>Channel</dt><dd>{frame.channel}</dd></div>}
        {frame.exposureSeconds!==undefined&&<div><dt>Exposure</dt><dd>{frame.exposureSeconds} seconds</dd></div>}
        {frame.flags?.length? <div><dt>Quality flags</dt><dd>{frame.flags.join(', ')}</dd></div>:null}
      </dl>}
      <p className="control-hint">Only metadata supplied by the backend is shown.</p>
      {searchWarnings?.map((s,i)=><p className="quality-warning" key={i}><AlertCircle size={14}/>{s}</p>)}
    </section>}
    {view==='explorer'&&explorerTab==='details'&&<section className="inspector-body">
      <div className="panel-section-title"><Crosshair size={15}/>Selection</div>
      {!selection?<div className="quiet-panel"><strong>No object selected</strong><span>Select a source in the image to inspect it.</span></div>:<div className="quiet-panel">
        <strong>{candidate?.label|| (candidate?'Unverified candidate':'Image selection')}</strong>
        {candidate?<><span>RA {candidate.raDeg.toFixed(6)}°</span><span>Dec {candidate.decDeg.toFixed(6)}°</span><span>Unverified candidate</span></>:<span>Image point {Math.round((selection.type==='image'?selection.point.xFraction:0)*100)}%, {Math.round((selection.type==='image'?selection.point.yFraction:0)*100)}%</span>}
      </div>}
      <div className="panel-divider"/>
      <div className="panel-section-title"><Layers size={15}/>Combine exposures</div>
      <p className="control-hint">Mean-combine every loaded real exposure to boost signal-to-noise. Averaging {frames.length} exposure{frames.length===1?'':'s'} reduces per-pixel noise by roughly {frames.length>1?`${Math.sqrt(frames.length).toFixed(1)}×`:'1×'}.</p>
      <button className="secondary-button full-button" type="button" disabled={frames.length<2||combineBusy} onClick={onGenerateCombine}><Layers size={16}/>{combineBusy?'Combining…':`Combine ${frames.length} exposures`}</button>
      {combine&&<div className="result-inline"><strong>Combined image loaded</strong><p>{combine.method||'Backend processing method not supplied.'}</p><button type="button" onClick={onClearCombine}>Return to original image</button></div>}
      {combineError&&<p className="inline-warning" role="alert">{combineError}</p>}{combine?.warnings?.map((s,i)=><p className="quality-warning" key={i}><AlertCircle size={14}/>{s}</p>)}
      {frames.length<2&&<p className="empty-text">At least two real observations are required.</p>}
      <div className="panel-divider"/>
      <div className="panel-section-title"><Sparkles size={15}/>Spectral fingerprint</div>
      {spectrumBusy?<p className="empty-text">Loading spectrum…</p>:spectrum?<><SpectrumPlot data={spectrum}/><small className="control-hint">{spectrum.samples.length} measured points · {spectrum.fluxUnit}</small></>:<div className="quiet-panel"><strong>No spectrum available</strong><span>Choose a source to request its spectrum.</span></div>}
      {spectrumError&&<p className="inline-warning" role="alert">{spectrumError}</p>}
      <div className="panel-divider"/>
      <div className="panel-section-title"><Radar size={15}/>Discovery candidates</div>
      {discovery?.candidates.length?<><p className="control-hint">{discovery.candidates.length} unverified candidates</p>{discovery.candidates.slice(0,5).map(c=><button key={c.id} type="button" className="compact-candidate" onClick={()=>onCandidate(c)}>{c.label||c.id}<span>Inspect</span></button>)}</>:<div className="quiet-panel"><strong>No candidates loaded</strong><span>Use Discover to inspect changes between observations.</span></div>}
      {frame?.flags?.length? <p className="quality-warning"><AlertCircle size={14}/>{frame.flags.join(', ')}</p>:null}
    </section>}
  </aside>
}
