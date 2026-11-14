import { useEffect, useRef, useState } from 'react'
import type { MouseEvent } from 'react'
import { Maximize, Minus, Plus, RotateCcw, ImageOff } from 'lucide-react'
import { imageURL } from '../services/api'
import type { Candidate, ImageLocation, Observation, OverlayResponse } from '../types/astronomy'

type Props = {
  frame:Observation|null;differenceUrl?:string;status:'idle'|'loading'|'ready'|'empty'|'error';error:string;
  candidates:Candidate[];gaia:OverlayResponse|null;brightness:number;contrast:number;inverted:boolean;
  onInspect:(p:ImageLocation)=>void;onCandidate:(c:Candidate)=>void;
}
export default function SkyViewer({frame,differenceUrl,status,error,candidates,gaia,brightness,contrast,inverted,onInspect,onCandidate}:Props) {
  const root=useRef<HTMLDivElement>(null),image=useRef<HTMLImageElement>(null)
  const [zoom,setZoom]=useState(1),[imageFailed,setImageFailed]=useState(false)
  useEffect(()=>{setZoom(1);setImageFailed(false)},[frame?.id,differenceUrl])
  const imageSrc=differenceUrl?imageURL(differenceUrl):frame?.imageUrl?imageURL(frame.imageUrl):null
  const show=!!imageSrc && !imageFailed
  function pick(e:MouseEvent<HTMLImageElement>) {
    if(!frame||differenceUrl||!image.current || !image.current.naturalWidth)return
    const node=image.current
    const box=node.getBoundingClientRect()
    const nativeRatio=node.naturalWidth/node.naturalHeight, boxRatio=box.width/box.height
    const actualWidth=boxRatio>nativeRatio?box.height*nativeRatio:box.width
    const actualHeight=boxRatio>nativeRatio?box.height:box.width/nativeRatio
    const x=(e.clientX-(box.left+(box.width-actualWidth)/2))/actualWidth
    const y=(e.clientY-(box.top+(box.height-actualHeight)/2))/actualHeight
    if(x<0||x>1||y<0||y>1)return
    onInspect({xFraction:x,yFraction:y})
  }
  async function fullscreen() {
    if(!root.current)return
    if(document.fullscreenElement) await document.exitFullscreen()
    else await root.current.requestFullscreen()
  }
  return <section className="sky-viewer" ref={root} aria-label="SPHEREx image viewer">
    {frame&&<div className="viewer-tag"><span>{differenceUrl?'Difference image':'SPHEREx observation'}</span>{!differenceUrl&&<span>{new Date(frame.observedAt).toLocaleString(undefined,{dateStyle:'medium',timeStyle:'short'})}</span>}</div>}
    <div className="viewer-tools" aria-label="Image zoom controls">
      <button title="Zoom in" aria-label="Zoom in" disabled={!show} type="button" onClick={()=>setZoom(z=>Math.min(5,+(z+.25).toFixed(2)))}><Plus size={17}/></button>
      <button title="Zoom out" aria-label="Zoom out" disabled={!show} type="button" onClick={()=>setZoom(z=>Math.max(1,+(z-.25).toFixed(2)))}><Minus size={17}/></button>
      <button title="Reset zoom" aria-label="Reset zoom" disabled={!show} type="button" onClick={()=>setZoom(1)}><RotateCcw size={16}/></button>
      <button title="Fullscreen" aria-label="Fullscreen" type="button" onClick={()=>void fullscreen()}><Maximize size={16}/></button>
    </div>
    {show&&<div className="sky-image-container">
      <div className="sky-image-layer" style={{transform:`scale(${zoom})`}}>
        <div className="sky-image-content">
          <img ref={image} src={imageSrc!} className="sky-image" alt={differenceUrl?'Difference image produced by the backend':'SPHEREx observation returned by the backend'} onError={()=>setImageFailed(true)} onClick={pick} draggable={false} style={{filter:`brightness(${brightness}%) contrast(${contrast}%) ${inverted?'invert(1)':''}`}}/>
          {!differenceUrl&&candidates.filter(c=>c.xFraction!==undefined&&c.yFraction!==undefined).map(c=><button key={c.id} className="sky-marker candidate-marker" title={c.label||`Unverified candidate ${c.id}`} aria-label={`Inspect unverified candidate ${c.label||c.id}`} type="button" style={{left:`${c.xFraction!*100}%`,top:`${c.yFraction!*100}%`}} onClick={e=>{e.stopPropagation();onCandidate(c)}}/>) }
          {!differenceUrl&&gaia?.sources.filter(s=>s.xFraction>=0&&s.xFraction<=1&&s.yFraction>=0&&s.yFraction<=1).map(s=><span key={s.id} title={s.label||`Gaia DR3 source ${s.id}`} className="sky-marker gaia-marker" style={{left:`${s.xFraction*100}%`,top:`${s.yFraction*100}%`}}/>) }
        </div>
      </div>
    </div>}
    {!show&&<div className="viewer-empty" role="status">
      {status==='loading'?<div className="loading-indicator"/>:<ImageOff size={35} strokeWidth={1.4}/>}
      <strong>{status==='loading'?'Loading data':status==='error'?'Unable to load data':imageFailed?'Unable to display image':'No data'}</strong>
      <span>{status==='loading'?'Retrieving real SPHEREx observations':status==='error'?error:imageFailed?'The backend image could not be loaded.':status==='empty'?'No observations returned for this search.':'Enter coordinates to load observations.'}</span>
    </div>}
    {frame&&<div className="viewer-bottom-info">{frame.release&&<span>{frame.release}</span>}{frame.detector&&<span>Detector {frame.detector}</span>}{frame.channel&&<span>Channel {frame.channel}</span>}{frame.flags&&frame.flags.length>0&&<span>{frame.flags.length} quality flag{frame.flags.length===1?'':'s'}</span>}{zoom!==1&&<span>Zoom {zoom.toFixed(2)}×</span>}</div>}
  </section>
}
