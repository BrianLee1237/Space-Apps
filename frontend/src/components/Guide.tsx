import { ChevronRight, Compass } from 'lucide-react'
export const guides=[
  {name:"Barnard's Star",subtitle:'High proper-motion star',hint:'Compare observations taken at different dates to look for a shift in position.'},
  {name:'Epsilon Indi B',subtitle:'Brown dwarf companions',hint:'Compare epochs around a known nearby brown-dwarf system.'},
  {name:'WISE 0855',subtitle:'Fast-moving brown dwarf',hint:'Watch for apparent movement between observations.'},
  {name:'RW Aurigae',subtitle:'Variable star',hint:'Look for brightness changes, not just position changes.'},
  {name:'R Draconis',subtitle:'Variable star',hint:'Compare measured brightness across observation dates.'},
]
export default function Guide({onSelect,loading}:{onSelect:(name:string)=>void;loading:boolean}) {
  return <section className="inspector-body guide-body"><p className="section-explainer">Explore the five test targets from the NASA challenge. Searches use the real data service.</p>
    {guides.map(item=><button key={item.name} className="guide-target" disabled={loading} type="button" onClick={()=>onSelect(item.name)}>
      <span className="guide-target-icon"><Compass size={17}/></span><span><strong>{item.name}</strong><small>{item.subtitle}</small><span className="guide-target-hint">{item.hint}</span></span><ChevronRight size={17}/>
    </button>)}
    <p className="control-hint">Four targets require the backend's astronomical name resolver. The NASA challenge supplies WISE 0855 coordinates directly.</p>
  </section>
}
