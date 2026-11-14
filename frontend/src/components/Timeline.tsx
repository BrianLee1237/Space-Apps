import { Pause, Play, SkipBack, SkipForward } from 'lucide-react'
import type { Observation } from '../types/astronomy'
export default function Timeline({frames,index,onIndex,playing,onPlaying,speed,onSpeed}:{
  frames:Observation[];index:number;onIndex:(n:number)=>void;playing:boolean;onPlaying:(b:boolean)=>void;speed:number;onSpeed:(n:number)=>void
}) {
  const has=frames.length>0,canPlay=frames.length>1
  const date=has?new Date(frames[index]?.observedAt).toLocaleString(undefined,{dateStyle:'medium',timeStyle:'short'}):'No observations'
  return <footer className="timeline" aria-label="Observation timeline">
    <div className="timeline-toolbar">
      <div className="player-controls">
        <button aria-label="Previous observation" type="button" onClick={()=>onIndex(Math.max(index-1,0))} disabled={!has||index===0}><SkipBack size={17}/></button>
        <button className="play-btn" aria-label={playing?'Pause playback':'Play observations'} type="button" onClick={()=>onPlaying(!playing)} disabled={!canPlay}>{playing?<Pause size={17} fill="currentColor"/>:<Play size={17} fill="currentColor"/>}</button>
        <button aria-label="Next observation" type="button" onClick={()=>onIndex(Math.min(index+1,frames.length-1))} disabled={!has||index>=frames.length-1}><SkipForward size={17}/></button>
      </div>
      <div className="timeline-date"><strong>{date}</strong><small>{has?`${index+1} of ${frames.length} epochs${index>0?' · '+((Date.parse(frames[index].observedAt)-Date.parse(frames[index-1].observedAt))/86400000).toFixed(1)+' days since previous':''}`:'No data loaded'}</small></div>
      <label className="speed-control">Speed<select aria-label="Playback speed" value={speed} onChange={e=>onSpeed(Number(e.target.value))}><option value={1200}>Slow</option><option value={700}>Normal</option><option value={300}>Fast</option></select></label>
    </div>
    <div className="timeline-track"><input type="range" aria-label="Observation number" min={0} max={Math.max(0,frames.length-1)} step={1} value={has?index:0} disabled={!has} onChange={e=>onIndex(Number(e.target.value))}/></div>
  </footer>
}
