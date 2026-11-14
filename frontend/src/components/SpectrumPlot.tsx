import type { SpectrumResponse } from '../types/astronomy'
export default function SpectrumPlot({data}:{data:SpectrumResponse}) {
  const points=data.samples
  if(points.length<2)return <p className="muted-message">Not enough spectral samples to plot.</p>
  const xMin=Math.min(...points.map(p=>p.wavelengthMicron)),xMax=Math.max(...points.map(p=>p.wavelengthMicron))
  const yMin=Math.min(...points.map(p=>p.flux-(p.uncertainty??0))),yMax=Math.max(...points.map(p=>p.flux+(p.uncertainty??0)))
  const x=(v:number)=>42+(v-xMin)/Math.max(1e-9,xMax-xMin)*252
  const y=(v:number)=>155-(v-yMin)/Math.max(1e-9,yMax-yMin)*126
  const poly=points.map(p=>`${x(p.wavelengthMicron).toFixed(2)},${y(p.flux).toFixed(2)}`).join(' ')
  return <div className="spectrum-plot" role="img" aria-label={`Spectrum with ${points.length} measured points from ${xMin.toFixed(2)} to ${xMax.toFixed(2)} micrometers` }>
    <svg viewBox="0 0 326 195" preserveAspectRatio="xMidYMid meet" aria-hidden="true">
      <path d="M42 24 V155 H301" fill="none" stroke="#617188" strokeWidth="1"/>
      {[0,.5,1].map(i=><line key={i} x1="42" x2="301" y1={155-i*126} y2={155-i*126} stroke="#2d3b4c" strokeDasharray="3 5"/>) }
      <polyline points={poly} fill="none" stroke="#51aaff" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round"/>
      {points.length<45&&points.map((p,i)=><circle key={i} cx={x(p.wavelengthMicron)} cy={y(p.flux)} r="2.4" fill="#8ecaff"/>)}
      <text x="42" y="175" className="plot-tick">{xMin.toFixed(2)}</text><text x="298" y="175" textAnchor="end" className="plot-tick">{xMax.toFixed(2)}</text>
      <text x="170" y="191" textAnchor="middle" className="plot-label">Wavelength (µm)</text>
      <text x="7" y="24" className="plot-label">Flux</text>
    </svg>
  </div>
}
