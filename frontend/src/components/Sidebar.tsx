import type { FormEvent } from 'react'
import {parseSkyCoordinates} from '../services/coordinates'
import { AlertCircle, Search, ChevronDown, Layers3, SquareDashed, SlidersHorizontal, Crosshair, X } from 'lucide-react'
import type { BandSelection, SearchTarget } from '../types/astronomy'

export default function Sidebar({ra,dec,onRa,onDec,fov,onFov,band,onBand,gaia,onGaia,hasFrames,gaiaWarnings,
  brightness,onBrightness,contrast,onContrast,inverted,onInvert,loading,onSearch,onClose,error}: {
    ra:string;dec:string;onRa:(v:string)=>void;onDec:(v:string)=>void;fov:number;onFov:(v:number)=>void;
    band:BandSelection;onBand:(b:BandSelection)=>void;gaia:boolean;onGaia:(b:boolean)=>void;hasFrames:boolean;gaiaWarnings?:string[];
    brightness:number;onBrightness:(n:number)=>void;contrast:number;onContrast:(n:number)=>void;
    inverted:boolean;onInvert:(b:boolean)=>void;loading:boolean;onSearch:(target:SearchTarget)=>void;onClose:()=>void;error?:string
  }) {
  const parsed=parseSkyCoordinates(ra,dec,fov)
  function submit(e:FormEvent) {e.preventDefault();if(parsed)onSearch(parsed)}
  return <aside className="sidebar" aria-label="Sky search and viewing settings">
    <div className="sidebar-heading"><span>Controls</span><button className="sidebar-dismiss" onClick={onClose} type="button" aria-label="Close controls"><X size={16}/></button></div>
    <form className="search-block" onSubmit={submit}>
      <div className="control-heading"><Crosshair size={16}/>Search sky</div>
      <label className="field-label" htmlFor="ra-input">Right ascension (RA)</label>
      <input id="ra-input" className="control-input" value={ra} onChange={e=>onRa(e.target.value)} placeholder="hh:mm:ss or degrees" autoComplete="off"/>
      <label className="field-label" htmlFor="dec-input">Declination (Dec)</label>
      <input id="dec-input" className="control-input" value={dec} onChange={e=>onDec(e.target.value)} placeholder="±dd:mm:ss or degrees" autoComplete="off"/>
      <button type="submit" className="primary-button" disabled={!parsed||loading}><Search size={16}/>{loading?'Loading…':'Search'}</button>
      {ra&&dec&&!parsed&&<p className="inline-warning" role="alert">Enter valid sky coordinates.</p>}
      {error&&<p className="inline-warning" role="alert">{error}</p>}
    </form>
    <section className="control-section">
      <div className="control-heading"><SquareDashed size={16}/>Field of view</div>
      <div className="select-shell"><select aria-label="Field of view" value={fov} onChange={e=>onFov(Number(e.target.value))}>
        {/* A shared/embedded URL can carry any value in the backend's supported
            0.5-60 arcmin range; show it even when it isn't one of the presets,
            instead of silently defaulting the dropdown's displayed value to 5. */}
        {!([5,10,15,30,60] as number[]).includes(fov)&&<option value={fov}>{fov} arcmin (from URL)</option>}
        {[5,10,15,30,60].map(v=><option key={v} value={v}>{v} arcmin</option>)}
      </select><ChevronDown size={15}/></div>
    </section>
    <section className="control-section">
      <div className="control-heading"><Layers3 size={16}/>SPHEREx wavelength</div>
      <div className="band-radio">
        {(['auto','detector','channel'] as const).map(mode=><label key={mode} className={`band-choice ${band.mode===mode?'band-choice-active':''}`}><input type="radio" name="bandmode" checked={band.mode===mode} onChange={()=>onBand(mode==='auto'?{mode:'auto'}:{mode,index:1})}/>{mode==='auto'?'Auto':mode==='detector'?'Detector (1–6)':'Channel (1–102)'}</label>)}
      </div>
      {band.mode!=='auto'&&<div className="band-number"><label htmlFor="band-index">{band.mode==='detector'?'Detector':'Channel'}</label><input id="band-index" type="number" min={1} max={band.mode==='detector'?6:102} value={band.index} onChange={e=>{
        const value=Number(e.target.value);if(Number.isInteger(value)&&value>=1&&value<=(band.mode==='detector'?6:102))onBand({...band,index:value})
      }}/></div>}
      <p className="control-hint">Available frames depend on the selected filter and archive coverage.</p>
    </section>
    <section className="control-section">
      <div className="control-heading"><Layers3 size={16}/>Catalog overlays</div>
      <label className={`toggle-row ${!hasFrames?'toggle-row-disabled':''}`}><span>Gaia DR3</span><input type="checkbox" role="switch" checked={gaia} disabled={!hasFrames} onChange={e=>onGaia(e.target.checked)}/><span className="toggle-track" aria-hidden="true"/></label>
      <p className="control-hint">Catalog sources are positioned by the backend using the image coordinates.</p>
      {gaia&&gaiaWarnings?.map((w,i)=><p className="quality-warning" key={i}><AlertCircle size={14}/>{w}</p>)}
    </section>
    <section className="control-section">
      <div className="control-heading"><SlidersHorizontal size={16}/>Image display</div>
      <label className="range-title" htmlFor="contrast-range">Contrast <span>{(contrast/100).toFixed(1)}×</span></label>
      <input id="contrast-range" type="range" min={50} max={200} step={5} value={contrast} onChange={e=>onContrast(Number(e.target.value))}/>
      <label className="range-title" htmlFor="brightness-range">Brightness <span>{(brightness/100).toFixed(1)}×</span></label>
      <input id="brightness-range" type="range" min={50} max={200} step={5} value={brightness} onChange={e=>onBrightness(Number(e.target.value))}/>
      <label className="toggle-row"><span>Invert colors</span><input type="checkbox" role="switch" checked={inverted} onChange={e=>onInvert(e.target.checked)}/><span className="toggle-track" aria-hidden="true"/></label>
      <p className="control-hint">These adjustments change the display, not the underlying measurements.</p>
    </section>
  </aside>
}
