import { useEffect, useRef, useState } from 'react'
import { X } from 'lucide-react'
import type { PointerEvent } from 'react'
import { imageURL } from '../services/api'
import type { Observation } from '../types/astronomy'

/** Two backend-provided, WCS-aligned observations. No interpolated sky data. */
export default function BeforeAfterSlider({earlier,later,onClose}:{earlier:Observation;later:Observation;onClose:()=>void}) {
  const [percent,setPercent]=useState(50)
  const [failed,setFailed]=useState(false)
  const stage=useRef<HTMLDivElement>(null)
  useEffect(()=>{setPercent(50);setFailed(false)},[earlier.id,later.id])
  const date=(value:string)=>new Date(value).toLocaleDateString(undefined,{year:'numeric',month:'short',day:'numeric'})
  function seek(e:PointerEvent<HTMLDivElement>){
    const rect=stage.current?.getBoundingClientRect()
    if(!rect)return
    setPercent(Math.min(100,Math.max(0,Math.round((e.clientX-rect.left)/rect.width*100))))
  }
  function down(e:PointerEvent<HTMLDivElement>){stage.current?.setPointerCapture(e.pointerId);seek(e)}
  function move(e:PointerEvent<HTMLDivElement>){if(e.buttons===1)seek(e)}
  return <section className="sky-viewer before-after-viewer" aria-label="Before and after comparison">
    <div className="comparison-heading">
      <div className="comparison-heading-label"><strong>Compare observations</strong><span>Drag the divider or use the slider below</span></div>
      <button type="button" className="comparison-close" onClick={onClose} aria-label="Close comparison and show original observation"><X size={15} aria-hidden="true"/> Show original</button>
    </div>
    {failed?<div className="comparison-failure" role="alert">One or both images could not be loaded. Try another pair.</div>:
      <div className="comparison-stage" ref={stage} onPointerDown={down} onPointerMove={move}>
        <img src={imageURL(later.imageUrl)} alt={`Later SPHEREx observation, ${date(later.observedAt)}`} draggable={false} onError={()=>setFailed(true)}/>
        <img src={imageURL(earlier.imageUrl)} className="comparison-before-image" style={{clipPath:`inset(0 ${100-percent}% 0 0)`}} alt={`Earlier SPHEREx observation, ${date(earlier.observedAt)}`} draggable={false} onError={()=>setFailed(true)}/>
        <div className="comparison-divider" style={{left:`${percent}%`}} aria-hidden="true"><span>⇔</span></div>
        <span className="comparison-image-label earlier">{date(earlier.observedAt)}</span><span className="comparison-image-label later">{date(later.observedAt)}</span>
      </div>}
    <label className="comparison-scrubber">Earlier / later
      <input aria-label="Before and after reveal" type="range" min={0} max={100} value={percent} onChange={e=>setPercent(Number(e.target.value))}/>
    </label>
    <p className="comparison-caveat">Two real exposures on a shared sky grid. Differences in wavelength, PSF and background can still mimic changes.</p>
  </section>
}
