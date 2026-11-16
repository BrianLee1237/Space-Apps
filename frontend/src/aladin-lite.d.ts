declare module 'aladin-lite' {
  export type HiPSSurvey = { setSliceNumber(index: number): void }
  export type AladinViewer = {
    setImageSurvey(survey: HiPSSurvey): void
    gotoRaDec(ra: number, dec: number): void
    setFoV(degrees: number): void
    on(
      event: string,
      callback: (position: {
        ra: number
        dec: number
        isDragging: boolean
      }) => void,
    ): void
  }
  const A: {
    init: Promise<void>
    aladin(element: HTMLElement, options: Record<string, unknown>): AladinViewer
    imageHiPS(url: string, options: Record<string, unknown>): HiPSSurvey
  }
  export default A
}
