import type { SavedFinding } from '../types/astronomy'
import { imageURL } from '../services/api'

/* Small dependency-free, locally generated PDF. Does not submit notes anywhere. */
const encoder=new TextEncoder()
const toBytes=(value:string)=>encoder.encode(value)
function concat(parts:Uint8Array[]):Uint8Array {
  const out=new Uint8Array(parts.reduce((n,p)=>n+p.length,0))
  let at=0
  for(const p of parts){out.set(p,at);at+=p.length}
  return out
}
const ascii=(value:string)=>value.normalize('NFKD')
  .replace(/[\u00b0]/g,' deg').replace(/[\u03bc\u00b5]/g,'u')
  .replace(/[\u2013\u2014]/g,'-').replace(/[\u2018\u2019]/g,"'")
  .replace(/[^\x20-\x7e]/g,'?')
const escapeText=(value:string)=>ascii(value).replace(/\\/g,'\\\\').replace(/\(/g,'\\(').replace(/\)/g,'\\)')

class PdfWriter {
  objects:Uint8Array[]=[]
  reserve(){this.objects.push(new Uint8Array());return this.objects.length}
  set(id:number,content:string|Uint8Array){this.objects[id-1]=typeof content==='string'?toBytes(content):content}
  add(content:string|Uint8Array){const id=this.reserve();this.set(id,content);return id}
  stream(bytes:Uint8Array,extra=''){
    return this.add(concat([toBytes(`<< /Length ${bytes.length} ${extra} >>\nstream\n`),bytes,toBytes('\nendstream')]))
  }
  finish(rootId:number){
    const parts: Uint8Array[]=[toBytes('%PDF-1.4\n%\xE2\xE3\xCF\xD3\n')]
    const offsets=[0]
    let position=parts[0].length
    for(let i=0;i<this.objects.length;i++){
      const b=concat([toBytes(`${i+1} 0 obj\n`),this.objects[i],toBytes('\nendobj\n')])
      offsets.push(position);parts.push(b);position+=b.length
    }
    const xref=position
    parts.push(toBytes(`xref\n0 ${this.objects.length+1}\n0000000000 65535 f \n`))
    for(const off of offsets.slice(1))parts.push(toBytes(`${String(off).padStart(10,'0')} 00000 n \n`))
    parts.push(toBytes(`trailer\n<< /Size ${this.objects.length+1} /Root ${rootId} 0 R >>\nstartxref\n${xref}\n%%EOF\n`))
    return concat(parts)
  }
}

function wrap(value:string,max=87):string[]{
  if(!value.trim())return ['']
  const result:string[]=[]
  for(const block of value.split('\n')){
    let line=''
    for(const word of ascii(block).split(/\s+/).filter(Boolean)){
      if(line.length && line.length+word.length+1>max){result.push(line);line=''}
      if(word.length>max){if(line){result.push(line);line=''}for(let p=0;p<word.length;p+=max)result.push(word.slice(p,p+max));continue}
      line+=(line?' ':'')+word
    }
    result.push(line)
  }
  return result
}

type ImageContent={label:string;id:string;date:string;data:Uint8Array;width:number;height:number}

async function readEvidenceImage(url:string):Promise<{bytes:Uint8Array;width:number;height:number}|null>{
  const response=await fetch(imageURL(url),{credentials:'same-origin'})
  if(!response.ok)throw new Error(`Image returned HTTP ${response.status}`)
  const bitmap=await createImageBitmap(await response.blob())
  try {
    const scale=Math.min(1,960/Math.max(bitmap.width,bitmap.height))
    const width=Math.max(1,Math.round(bitmap.width*scale)),height=Math.max(1,Math.round(bitmap.height*scale))
    const canvas=document.createElement('canvas');canvas.width=width;canvas.height=height
    const ctx=canvas.getContext('2d')
    if(!ctx)return null
    ctx.fillStyle='#ffffff';ctx.fillRect(0,0,width,height)
    ctx.drawImage(bitmap,0,0,width,height)
    const b64=canvas.toDataURL('image/jpeg',0.87).split(',')[1]
    const str=atob(b64);const bytes=new Uint8Array(str.length)
    for(let i=0;i<str.length;i++)bytes[i]=str.charCodeAt(i)
    return {bytes,width,height}
  } finally {bitmap.close()}
}

export async function buildDiscoveryReport(record:SavedFinding):Promise<Uint8Array>{
  const images:ImageContent[]=[]
  const refs=record.observations.filter(o=>o.imageUrl)
  const chosen=refs.length>1?[refs[0],refs[refs.length-1]]:refs
  const notes:string[]=[]
  for(const entry of chosen){
    try{
      const rendered=await readEvidenceImage(entry.imageUrl!)
      if(rendered)images.push({label:'SPHEREx observation',id:entry.id,date:entry.observedAt,data:rendered.bytes,width:rendered.width,height:rendered.height})
      else notes.push(`Could not embed image ${entry.id}: browser image processing unavailable.`)
    }catch{notes.push(`Could not embed image ${entry.id}: the archive preview was unavailable.`)}
  }
  const pdf=new PdfWriter()
  const catalog=pdf.reserve(),pages=pdf.reserve(),font=pdf.add('<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>')
  const pageIds:number[]=[]
  let cmds:string[]=[],y=775
  const text=(value:string,size=10,bold=false)=>{
    const safe=escapeText(value)
    cmds.push(`BT /F1 ${size} Tf 0.12 0.16 0.19 rg 55 ${y.toFixed(1)} Td (${safe}) Tj ET`)
    y-=size*1.65+(bold?5:1)
  }
  const flush=()=>{
    const stream=pdf.stream(toBytes(cmds.join('\n')))
    pageIds.push(pdf.add(`<< /Type /Page /Parent ${pages} 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 ${font} 0 R >> >> /Contents ${stream} 0 R >>`))
    cmds=[];y=775
  }
  const line=(value:string,size=10)=>{if(y<68)flush();text(value,size)}
  const section=(value:string)=>{if(y<115)flush();y-=9;line(value,13)}
  line('SPHEREx observation report',21);y-=6
  line(`Saved: ${record.savedAt}`)
  line(`RA ${record.target.raDeg.toFixed(7)} deg  |  Dec ${record.target.decDeg.toFixed(7)} deg`)
  line(`Field: ${record.target.fovArcmin} arcmin  |  Target: ${record.target.name||'Coordinate selection'}`)
  line('Data: SPHEREx / NASA IRSA public archive, retrieved via SKYFRAME OBSERVATORY')
  section('Notes')
  for(const part of wrap(record.note||'No notes entered.'))line(part)
  if(record.analysis){
    section('Analysis provenance')
    line(`Algorithm version: ${record.analysis.provenance.algorithmVersion}`)
    for(const part of wrap(`Software SHA256: ${record.analysis.provenance.codeSha256}`))line(part)
    for(const part of wrap(`Calibration SHA256: ${record.analysis.provenance.calibrationSha256}`))line(part)
    line('The complete measurement record is attached as spherex-evidence.json.')
  }
  if(record.candidate){
    section('Unverified candidate')
    line(`ID: ${record.candidate.id}  |  RA ${record.candidate.raDeg.toFixed(6)} deg, Dec ${record.candidate.decDeg.toFixed(6)} deg`)
    for(const part of wrap(record.candidate.caption||record.candidate.notes||'Candidate not independently confirmed.'))line(part)
  }
  if(record.motionSummary){
    section('Apparent centroid displacement (unverified)')
    const m=record.motionSummary
    line(`${m.observationsMeasured} matched frames; ${m.baselineDays} days between earliest and latest.`)
    line(`${m.apparentShiftArcsec} arcsec shift; apparent rate ${m.apparentRateArcsecPerYear??'unavailable'} arcsec/year.`)
    line('These are quick-look associations, NOT a validated physical proper-motion measurement.')
  }
  section('Observation dates and evidence IDs')
  for(const o of record.observations){
    const date=`${o.observedAt} | ${o.release||'release unspecified'} | D${o.detector??'?'} | ${o.centralWavelengthMicron?.toFixed(4)??'wavelength unknown'} um`
    for(const part of wrap(date,88))line(part)
    for(const part of wrap(`ID: ${o.id}`,88))line(part)
    if(o.flags?.length)for(const part of wrap(`Flags: ${o.flags.join(', ')}`,88))line(part)
  }
  section('Uncertainties and limitations')
  for(const value of [...(record.analysisWarnings||[]),...notes,
    'Image differences may result from wavelength, PSF, calibration, coverage or cosmic-ray artifacts.',
    'This report is a saved observation record, not confirmation of a new astronomical object.']){
    for(const part of wrap(value,88))line(part)
  }
  line('Archive: https://irsa.ipac.caltech.edu/Missions/spherex.html')
  flush()
  for(const image of images){
    const imgId=pdf.stream(image.data,`/Type /XObject /Subtype /Image /Width ${image.width} /Height ${image.height} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode`)
    const w=Math.min(478, image.width*478/Math.max(image.width,image.height))
    const h=w*image.height/image.width
    const drawing=[
      'BT /F1 17 Tf 0.12 0.16 0.19 rg 55 775 Td (Archive image evidence) Tj ET',
      `BT /F1 10 Tf 0.12 0.16 0.19 rg 55 746 Td (${escapeText(image.date)}) Tj ET`,
      `q ${w.toFixed(2)} 0 0 ${h.toFixed(2)} ${((595-w)/2).toFixed(2)} ${(690-h).toFixed(2)} cm /Im0 Do Q`,
      `BT /F1 8 Tf 0.12 0.16 0.19 rg 55 120 Td (ID: ${escapeText(image.id)}) Tj ET`,
      'BT /F1 9 Tf 0.12 0.16 0.19 rg 55 94 Td (Actual archive preview, displayed with a visual stretch.) Tj ET',
    ]
    const stream=pdf.stream(toBytes(drawing.join('\n')))
    pageIds.push(pdf.add(`<< /Type /Page /Parent ${pages} 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 ${font} 0 R >> /XObject << /Im0 ${imgId} 0 R >> >> /Contents ${stream} 0 R >>`))
  }
  pdf.set(pages,`<< /Type /Pages /Count ${pageIds.length} /Kids [${pageIds.map(id=>`${id} 0 R`).join(' ')}] >>`)
  const evidence=pdf.stream(toBytes(JSON.stringify(record,null,2)),'/Type /EmbeddedFile /Subtype /application#2Fjson')
  const specification=pdf.add(`<< /Type /Filespec /F (spherex-evidence.json) /EF << /F ${evidence} 0 R >> >>`)
  pdf.set(catalog,`<< /Type /Catalog /Pages ${pages} 0 R /Names << /EmbeddedFiles << /Names [(spherex-evidence.json) ${specification} 0 R] >> >> >>`)
  return pdf.finish(catalog)
}

export async function downloadDiscoveryPdf(record:SavedFinding){
  const bytes=await buildDiscoveryReport(record)
  const blob=new Blob([Uint8Array.from(bytes)],{type:'application/pdf'})
  const url=URL.createObjectURL(blob)
  const link=document.createElement('a');link.href=url
  link.download=`spherex-report-${record.id.replace(/[^a-zA-Z0-9_-]/g,'')}.pdf`
  document.body.appendChild(link);link.click();link.remove()
  window.setTimeout(()=>URL.revokeObjectURL(url),1500)
}
