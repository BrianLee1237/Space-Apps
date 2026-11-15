import { ChevronRight, Compass, CheckCircle2 } from 'lucide-react'
import type { Observation, MatchedPair } from '../types/astronomy'
export const guides=[
  {name:"Barnard's Star",subtitle:'High proper-motion star',hint:'Track a bright source across dates; a displacement must be measured, not assumed.'},
  {name:'Epsilon Indi B',subtitle:'Brown dwarf system',hint:'Compare wavelength-matched exposures and look for small shifts.'},
  {name:'WISE 0855',subtitle:'Nearby brown dwarf',hint:'Inspect residuals in different epochs and distinguish motion from detector artifacts.'},
  {name:'RW Aurigae',subtitle:'Variable star',hint:'Look for changes in brightness while accounting for wavelength differences.'},
  {name:'R Draconis',subtitle:'Variable star',hint:'Choose comparable epochs and inspect measured flux and its uncertainty.'},
]
export default function Guide({onSelect,loading,active,frames,pair,onCompare,onDiscover,onMotion,onNotebook}:{
  onSelect:(name:string)=>void;loading:boolean;active:string|null;frames:Observation[];pair:MatchedPair|null;
  onCompare:()=>void;onDiscover:()=>void;onMotion:()=>void;onNotebook:()=>void
}) {
  const chosen=guides.find(g=>g.name===active)
  return <section className="inspector-body guide-body">
    <p className="section-explainer">Start with a known test target, then inspect real SPHEREx observations.</p>
    {chosen&&<div className="guided-steps" aria-live="polite">
      <strong>{chosen.name}</strong><p>{chosen.hint}</p>
      <div><CheckCircle2 size={14}/><span>{frames.length?`${frames.length} dated observations loaded`:'Search the archive for observations'}</span></div>
      <div><CheckCircle2 size={14}/><span>{pair?`Matched pair: ${pair.elapsedDays.toFixed(0)} days apart`:'Choose comparable dates and wavelengths'}</span></div>
      <button type="button" disabled={!frames.length} onClick={onCompare}>Compare observations</button>
      <button type="button" disabled={frames.length<2} onClick={onDiscover}>Check for candidates</button>
      <button type="button" disabled={!frames.length} onClick={onMotion}>Track a selected source</button>
      <button type="button" disabled={!frames.length} onClick={onNotebook}>Save findings</button>
      <small>Only report changes supported by the actual observations. Empty results are valid.</small>
    </div>}
    {guides.map(item=><button key={item.name} className={`guide-target ${active===item.name?'guide-target-selected':''}`} disabled={loading} type="button" onClick={()=>onSelect(item.name)}>
      <span className="guide-target-icon"><Compass size={17}/></span><span><strong>{item.name}</strong><small>{item.subtitle}</small></span><ChevronRight size={17}/>
    </button>)}
  </section>
}
