import { useEffect, useRef, useState } from 'react'
import { AlertTriangle } from 'lucide-react'
import Navbar from '../components/Navbar'
import Sidebar, { parseSkyCoordinates } from '../components/Sidebar'
import SkyViewer from '../components/SkyViewer'
import Timeline from '../components/Timeline'
import Inspector from '../components/Inspector'
import { getCandidates,getDifference,getGaiaOverlay,getObservations,getSpectrum,resolveTarget } from '../services/api'
import type { BandSelection,Candidate,DifferenceResponse,DiscoveryResponse,ImageLocation,Observation,OverlayResponse,SavedFinding,SearchTarget,SpectrumResponse,ViewName } from '../types/astronomy'

type LoadStatus='idle'|'loading'|'ready'|'empty'|'error'
type Selection={type:'image';point:ImageLocation}|{type:'candidate';candidate:Candidate}|null
const WISE0855:SearchTarget={name:'WISE 0855',raDeg:(8+55/60+10.831/3600)*15,decDeg:-(7+14/60+42.53/3600),fovArcmin:10}
const NOTES_KEY='spherex-explorer-notes-v1'
function readNotes():SavedFinding[] {
  try {const value=JSON.parse(localStorage.getItem(NOTES_KEY)||'[]') as unknown;return Array.isArray(value)?value.filter(v=>v&&typeof v==='object'&&typeof v.id==='string'):[]}catch{return []}
}
export default function Explorer(){
  const [view,setView]=useState<ViewName>('explorer')
  const [settingsOpen,setSettingsOpen]=useState(()=>window.innerWidth>=950)
  const [ra,setRa]=useState(''),[dec,setDec]=useState(''),[fov,setFov]=useState(10)
  const [band,setBand]=useState<BandSelection>({mode:'auto'})
  const [target,setTarget]=useState<SearchTarget|null>(null)
  const [status,setStatus]=useState<LoadStatus>('idle'),[loadError,setLoadError]=useState('')
  const [frames,setFrames]=useState<Observation[]>([]),[index,setIndex]=useState(0)
  const [playing,setPlaying]=useState(false),[speed,setSpeed]=useState(700)
  const [brightness,setBrightness]=useState(100),[contrast,setContrast]=useState(100),[inverted,setInverted]=useState(false)
  const [gaiaEnabled,setGaiaEnabled]=useState(false),[gaia,setGaia]=useState<OverlayResponse|null>(null)
  const [selection,setSelection]=useState<Selection>(null)
  const [spectrum,setSpectrum]=useState<SpectrumResponse|null>(null),[spectrumBusy,setSpectrumBusy]=useState(false),[spectrumError,setSpectrumError]=useState('')
  const [discovery,setDiscovery]=useState<DiscoveryResponse|null>(null),[discoveryBusy,setDiscoveryBusy]=useState(false),[discoveryError,setDiscoveryError]=useState('')
  const [diff,setDiff]=useState<DifferenceResponse|null>(null),[diffBusy,setDiffBusy]=useState(false),[diffError,setDiffError]=useState('')
  const [from,setFrom]=useState(0),[to,setTo]=useState(1)
  const [guideBusy,setGuideBusy]=useState(false)
  const [notes,setNotes]=useState<SavedFinding[]>(readNotes)
  const abort=useRef<AbortController|null>(null),seq=useRef(0)
  const frame=frames[index]??null

  useEffect(()=>{try{localStorage.setItem(NOTES_KEY,JSON.stringify(notes))}catch{/* Private-browsing storage can fail. */}},[notes])
  useEffect(()=>{if(!playing||frames.length<2)return;const handle=window.setInterval(()=>setIndex(i=>(i+1)%frames.length),speed);return()=>window.clearInterval(handle)},[playing,frames.length,speed])
  useEffect(()=>{
    if(!gaiaEnabled||!frame){setGaia(null);return}
    const ctrl=new AbortController();setGaia(null)
    void getGaiaOverlay(frame.id,ctrl.signal).then(setGaia).catch(e=>{if(!ctrl.signal.aborted)setLoadError(e instanceof Error?e.message:'Unable to load Gaia overlay.')})
    return()=>ctrl.abort()
  },[gaiaEnabled,frame?.id]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(()=>{const params=new URLSearchParams(window.location.search)
    const rawRa=params.get('ra'),rawDec=params.get('dec'),rawFov=Number(params.get('fov')||10)
    if(rawRa===null||rawDec===null)return
    const fovValue=[5,10,15,30,60].includes(rawFov)?rawFov:10
    const position=parseSkyCoordinates(rawRa,rawDec,fovValue)
    if(!position)return
    const mode=params.get('mode'),value=Number(params.get('index'))
    const nextBand:BandSelection=mode==='detector'&&Number.isInteger(value)&&value>=1&&value<=6?{mode:'detector',index:value}:
      mode==='channel'&&Number.isInteger(value)&&value>=1&&value<=102?{mode:'channel',index:value}:{mode:'auto'}
    setRa(rawRa);setDec(rawDec);setFov(fovValue);setBand(nextBand)
    void loadObservations(position,nextBand)
  },[]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(()=>()=>{abort.current?.abort()},[])

  async function loadObservations(next:SearchTarget,nextBand:BandSelection=band) {
    abort.current?.abort();const ctrl=new AbortController();abort.current=ctrl;const requestId=++seq.current
    setTarget(next);setFrames([]);setIndex(0);setPlaying(false);setLoadError('');setStatus('loading');
    setSpectrum(null);setSelection(null);setDiscovery(null);setDiff(null);setGaia(null);setGaiaEnabled(false);setDiscoveryError('');setSpectrumError('');setDiffError('');
    setRa(String(next.raDeg));setDec(String(next.decDeg));setFov(next.fovArcmin)
    const url=new URL(window.location.href);url.searchParams.set('ra',String(next.raDeg));url.searchParams.set('dec',String(next.decDeg));url.searchParams.set('fov',String(next.fovArcmin));url.searchParams.set('mode',nextBand.mode)
    if('index' in nextBand)url.searchParams.set('index',String(nextBand.index));else url.searchParams.delete('index')
    window.history.replaceState({},'',url.pathname+url.search+url.hash)
    try{const data=await getObservations(next,nextBand,ctrl.signal);if(ctrl.signal.aborted||seq.current!==requestId)return
      setFrames(data.observations);setStatus(data.observations.length?'ready':'empty');setTo(data.observations.length>1?1:0);setFrom(0)
    }catch(e){if(ctrl.signal.aborted||seq.current!==requestId)return;setLoadError(e instanceof Error?e.message:'Unable to load observations.');setStatus('error')}
  }
  function updateBand(next:BandSelection){setBand(next);if(target)void loadObservations(target,next)}
  function updateFov(next:number){setFov(next);if(target)void loadObservations({...target,fovArcmin:next})}
  function changeIndex(i:number){setIndex(i);setPlaying(false);setDiff(null);setSpectrum(null);setSelection(null)}
  async function inspect(point:ImageLocation){if(!frame)return;setSelection({type:'image',point});setSpectrum(null);setSpectrumError('');setSpectrumBusy(true)
    try{setSpectrum(await getSpectrum({observationId:frame.id,xFraction:point.xFraction,yFraction:point.yFraction}))}
    catch(e){setSpectrumError(e instanceof Error?e.message:'No spectrum available.')}
    finally{setSpectrumBusy(false)}
  }
  async function inspectCandidate(candidate:Candidate){setSelection({type:'candidate',candidate});setView('spectrum');setSpectrum(null);setSpectrumError('');setSpectrumBusy(true)
    try{setSpectrum(await getSpectrum({raDeg:candidate.raDeg,decDeg:candidate.decDeg}))}
    catch(e){setSpectrumError(e instanceof Error?e.message:'No spectrum available.')}
    finally{setSpectrumBusy(false)}
  }
  async function scan(){if(!target||frames.length<2)return;setDiscovery(null);setDiscoveryError('');setDiscoveryBusy(true)
    try{setDiscovery(await getCandidates(target,frames))}
    catch(e){setDiscoveryError(e instanceof Error?e.message:'Candidate scan unavailable.')}
    finally{setDiscoveryBusy(false)}
  }
  async function compare(){if(frames.length<2||from===to)return;setDiff(null);setDiffError('');setDiffBusy(true);setPlaying(false)
    try{setDiff(await getDifference(frames[from].id,frames[to].id))}
    catch(e){setDiffError(e instanceof Error?e.message:'Unable to generate difference image.')}
    finally{setDiffBusy(false)}
  }
  async function guidedSearch(name:string){setGuideBusy(true);setLoadError('')
    try{
      if(name==='WISE 0855'){setView('explorer');await loadObservations({...WISE0855,fovArcmin:fov});return}
      const result=await resolveTarget(name)
      setView('explorer');await loadObservations({...result,name,fovArcmin:fov})
    }catch(e){setView('explorer');setFrames([]);setIndex(0);setTarget(null);setLoadError(e instanceof Error?e.message:'Unable to resolve target.');setStatus('error')}
    finally{setGuideBusy(false)}
  }
  function saveNote(note:string){if(!target||!frames.length)return
    const finding:SavedFinding={id:crypto.randomUUID?.()??String(Date.now()),savedAt:new Date().toISOString(),note,target,candidate:selection?.type==='candidate'?selection.candidate:undefined,
      selectedObservationId:frame?.id,observations:frames.map(o=>({id:o.id,observedAt:o.observedAt,release:o.release,flags:o.flags}))}
    setNotes(old=>[finding,...old])
  }
  return <div className="app-shell">
    <Navbar view={view} onView={setView} settingsOpen={settingsOpen} onToggleSettings={()=>setSettingsOpen(v=>!v)}/>
    <div className={`workspace ${settingsOpen?'workspace-with-settings':'workspace-no-settings'}`}>
      {settingsOpen&&<Sidebar ra={ra} dec={dec} onRa={setRa} onDec={setDec} fov={fov} onFov={updateFov} band={band} onBand={updateBand} gaia={gaiaEnabled} onGaia={setGaiaEnabled} hasFrames={!!frame} brightness={brightness} onBrightness={setBrightness} contrast={contrast} onContrast={setContrast} inverted={inverted} onInvert={setInverted} loading={status==='loading'} error={status==='error'?loadError:''} onSearch={t=>{setView('explorer');void loadObservations(t)}} onClose={()=>setSettingsOpen(false)}/>}
      <div className="viewer-workspace"><SkyViewer frame={frame} differenceUrl={diff?.imageUrl} status={status} error={loadError} candidates={discovery?.candidates??[]} gaia={gaia} brightness={brightness} contrast={contrast} inverted={inverted} onInspect={p=>void inspect(p)} onCandidate={c=>void inspectCandidate(c)}/>
        {loadError&&status==='ready'&&<div className="overlay-error" role="alert"><AlertTriangle size={15}/>{loadError}<button type="button" onClick={()=>setLoadError('')} aria-label="Dismiss error">×</button></div>}
      </div>
      <Inspector view={view} frame={frame} frames={frames} selection={selection} spectrum={spectrum} spectrumBusy={spectrumBusy} spectrumError={spectrumError} discovery={discovery} discoveryBusy={discoveryBusy} discoveryError={discoveryError} onScan={()=>void scan()} onCandidate={c=>void inspectCandidate(c)} diff={diff} diffBusy={diffBusy} diffError={diffError} compareFrom={from} compareTo={to} onFrom={setFrom} onTo={setTo} onGenerateDifference={()=>void compare()} onClearDifference={()=>setDiff(null)} target={target} notes={notes} onSaveNote={saveNote} onDeleteNote={id=>setNotes(v=>v.filter(item=>item.id!==id))} onGuideTarget={name=>void guidedSearch(name)} guideBusy={guideBusy}/>
      <Timeline frames={frames} index={index} onIndex={changeIndex} playing={playing} onPlaying={setPlaying} speed={speed} onSpeed={setSpeed}/>
    </div>
  </div>
}
