import A from 'aladin-lite'
import type { AladinViewer, HiPSSurvey } from 'aladin-lite'

let viewer: AladinViewer | null = null,
  survey: HiPSSurvey | null = null
let configuration = { channel: 86, ra: 0, dec: 0, fov: 1 }
function apply() {
  viewer?.gotoRaDec(configuration.ra, configuration.dec)
  viewer?.setFoV(configuration.fov)
  survey?.setSliceNumber(configuration.channel - 1)
}
window.addEventListener('message', (event) => {
  if (
    event.origin !== location.origin ||
    event.source !== parent ||
    event.data?.type !== 'atlas-config'
  )
    return
  const { channel, ra, dec, fov } = event.data
  if (
    ![channel, ra, dec, fov].every(Number.isFinite) ||
    channel < 1 ||
    channel > 102 ||
    fov <= 0
  )
    return
  configuration = { channel, ra, dec, fov }
  apply()
})
void A.init
  .then(() => {
    survey = A.imageHiPS(
      'https://irsa.ipac.caltech.edu/data/hips/SPHEREx/spherex_allsky_cube',
      {
        name: 'SPHEREx DR1 wavelength mosaic',
        imgFormat: 'png',
        successCallback: (layer: HiPSSurvey) => {
          survey = layer
          apply()
          parent.postMessage({ type: 'atlas-ready' }, location.origin)
        },
        errorCallback: () =>
          parent.postMessage(
            {
              type: 'atlas-error',
              message: 'The IRSA mosaic could not be retrieved.',
            },
            location.origin,
          ),
      },
    )
    viewer = A.aladin(document.getElementById('atlas')!, {
      survey: survey,
      target: `${configuration.ra} ${configuration.dec}`,
      fov: configuration.fov,
      cooFrame: 'ICRS',
      mode: 'dark',
      log: false,
      showLayersControl: false,
      showShareControl: false,
      showFullscreenControl: false,
      showSimbadPointerControl: false,
      showCooGridControl: true,
    })
    viewer.on('click', (position) => {
      if (!position.isDragging)
        parent.postMessage(
          { type: 'atlas-picked', ra: position.ra, dec: position.dec },
          location.origin,
        )
    })
  })
  .catch((reason) =>
    parent.postMessage(
      { type: 'atlas-error', message: String(reason) },
      location.origin,
    ),
  )
