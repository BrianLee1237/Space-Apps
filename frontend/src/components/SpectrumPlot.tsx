import type { SpectrumResponse } from '../types/astronomy'
export default function SpectrumPlot({data}:{data:SpectrumResponse}) {
  const points=data.samples
  if(points.length<2)return <p className="muted-message">Not enough spectral samples to plot.</p>
  const xMin=Math.min(...points.map(p=>p.wavelengthMicron)),xMax=Math.max(...points.map(p=>p.wavelengthMicron))
  const yMin=Math.min(...points.map(p=>p.flux-(p.uncertainty??0))),yMax=Math.max(...points.map(p=>p.flux+(p.uncertainty??0)))
  const x=(v:number)=>42+(v-xMin)/Math.max(1e-9,xMax-xMin)*252
  const y=(v:number)=>155-(v-yMin)/Math.max(1e-9,yMax-yMin)*126
  return <div className="spectrum-plot" role="img" aria-label={`Spectrum with ${points.length} measured points from ${xMin.toFixed(2)} to ${xMax.toFixed(2)} micrometers` }>
    <svg viewBox="0 0 326 195" preserveAspectRatio="xMidYMid meet" aria-hidden="true">
      <path d="M42 24 V155 H301" fill="none" stroke="#737570" strokeWidth="1"/>
      {[0,.5,1].map(i=><line key={i} x1="42" x2="301" y1={155-i*126} y2={155-i*126} stroke="#333938" strokeDasharray="3 5"/>) }
      {points.map((p,i)=><g key={i}>
        <title>{p.wavelengthMicron.toFixed(4)} µm · {p.flux.toPrecision(4)} {data.fluxUnit}{p.observedAt?` · ${new Date(p.observedAt).toLocaleString()}`:''}</title>
        {p.uncertainty!=null&&<line x1={x(p.wavelengthMicron)} x2={x(p.wavelengthMicron)} y1={y(p.flux-p.uncertainty)} y2={y(p.flux+p.uncertainty)} stroke="#c4a06b" strokeWidth="1"/>}
        <circle cx={x(p.wavelengthMicron)} cy={y(p.flux)} r="2.6" fill="#f1c48a"/>
      </g>)}
      <text x="42" y="175" className="plot-tick">{xMin.toFixed(2)}</text><text x="298" y="175" textAnchor="end" className="plot-tick">{xMax.toFixed(2)}</text>
      <text x="170" y="191" textAnchor="middle" className="plot-label">Wavelength (µm)</text>
      <text x="42" y="17" className="plot-label">{data.fluxUnit}</text>
      <text x="38" y="31" textAnchor="end" className="plot-tick">{yMax.toPrecision(2)}</text>
      <text x="38" y="155" textAnchor="end" className="plot-tick">{yMin.toPrecision(2)}</text>
    </svg>
  </div>
}
