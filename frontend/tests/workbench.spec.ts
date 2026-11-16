import { expect, test } from '@playwright/test'

const search = 'a'.repeat(24)
const frames = Array.from({ length: 12 }, (_, i) => ({
  id: `${search}.${i.toString(16).padStart(24, '0')}`,
  observedAt: new Date(Date.UTC(2025, 0, 1 + i * 5)).toISOString(),
  imageUrl: `/api/images/frame-${i}.png`,
  release: 'DR1',
  detector: 6,
  imageAligned: true,
}))
const pair = {
  fromId: frames[1].id,
  toId: frames[10].id,
  earlierAt: frames[1].observedAt,
  laterAt: frames[10].observedAt,
  elapsedDays: 45,
  detector: 6,
  wavelengthMicron: 4.5,
  wavelengthDifferencePercent: 0.1,
  hasQualityFlags: false,
}
const png = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAYAAADED76LAAAAFklEQVR4nGO8c2nffwY8gAmf5PBRAACHFwN7Rgf/0wAAAABJRU5ErkJggg==',
  'base64',
)

test('analysis receives the full search while playback is time-thinned', async ({
  page,
}) => {
  let matchedIds: string[] = []
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname.startsWith('/api/images/')) {
      await route.fulfill({ contentType: 'image/png', body: png })
      return
    }
    if (url.pathname === '/api/observations') {
      await route.fulfill({ json: { observations: frames } })
      return
    }
    if (url.pathname === '/api/metadata') {
      await route.fulfill({
        json: { id: url.searchParams.get('observationId'), flags: [] },
      })
      return
    }
    if (url.pathname === '/api/science/jobs') {
      const request = route.request().postDataJSON()
      matchedIds = request.ids
      await route.fulfill({
        json: {
          id: 'job',
          subscription: 'browser',
          state: 'complete',
          completed: 12,
          total: 12,
          result: {
            pairs: [pair],
            inspected: 12,
            warnings: [],
            method: 'Test fixture',
            provenance: {},
          },
          error: null,
        },
      })
      return
    }
    await route.fulfill({ json: {} })
  })
  await page.goto('/?ra=133.7&dec=-7.2&fov=10')
  await expect(page.getByText('2 playback epochs / 12 exposures')).toBeVisible()
  await page.getByRole('button', { name: 'Compare', exact: true }).click()
  await page
    .getByRole('button', { name: 'Find comparable epochs', exact: true })
    .click()
  await expect(page.getByText('1 compatible pairs found')).toBeVisible()
  expect(matchedIds).toHaveLength(12)
  await page
    .getByRole('button', { name: 'Open before/after slider', exact: true })
    .click()
  await expect(
    page.getByRole('region', { name: 'Before and after comparison' }),
  ).toBeVisible()
  await page
    .getByRole('button', { name: 'Play observations', exact: true })
    .click()
  await expect(
    page.getByRole('region', { name: 'SPHEREx image viewer' }),
  ).toBeVisible()
})

test('source selection opens cancellable scientific tools on mobile', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.route('**/api/**', async (route) => {
    if (route.request().url().includes('/images/'))
      await route.fulfill({ contentType: 'image/png', body: png })
    else if (route.request().url().includes('/observations?'))
      await route.fulfill({ json: { observations: frames } })
    else await route.fulfill({ json: { samples: [], fluxUnit: 'MJy/sr' } })
  })
  await page.goto('/?ra=133.7&dec=-7.2&fov=10')
  await page
    .getByRole('button', { name: 'Close controls', exact: true })
    .click()
  await page
    .locator('.sky-image')
    .evaluate((image: HTMLImageElement) => image.decode())
  await page.locator('.sky-image').click()
  await page.getByRole('button', { name: 'Science', exact: true }).click()
  await expect(
    page.getByRole('button', { name: 'Measure light curve', exact: true }),
  ).toBeEnabled()
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true)
})

test('Gaia failure stays in the catalog panel and can recover', async ({
  page,
}) => {
  let unavailable = true
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname.startsWith('/api/images/'))
      await route.fulfill({ contentType: 'image/png', body: png })
    else if (url.pathname === '/api/observations')
      await route.fulfill({ json: { observations: frames } })
    else if (url.pathname === '/api/overlays') {
      if (unavailable)
        await route.fulfill({
          status: 502,
          json: { detail: 'Catalog provider unavailable' },
        })
      else
        await route.fulfill({
          json: {
            sources: [
              {
                id: 'fixture',
                label: 'Gaia DR3 test catalog row',
                xFraction: 0.7,
                yFraction: 0.2,
              },
            ],
            warnings: [],
          },
        })
    } else await route.fulfill({ json: {} })
  })
  await page.goto('/?ra=133.7&dec=-7.2&fov=10')
  await expect(page.locator('.sky-image')).toBeVisible()
  await page.getByRole('switch', { name: 'Gaia DR3' }).check()
  await expect(
    page.getByText('Catalog provider unavailable', { exact: true }),
  ).toBeVisible()
  await expect(page.locator('.sky-image')).toBeVisible()
  await expect(
    page.getByText('Unable to load data', { exact: true }),
  ).toHaveCount(0)
  await page.getByRole('switch', { name: 'Gaia DR3' }).uncheck()
  unavailable = false
  await page.getByRole('switch', { name: 'Gaia DR3' }).check()
  await expect(page.getByTitle('Gaia DR3 test catalog row')).toBeVisible()
  await expect(
    page.getByText('Catalog provider unavailable', { exact: true }),
  ).toHaveCount(0)
})

test('playback waits for an exposure to load before advancing again', async ({
  page,
}) => {
  let release: () => void = () => {}
  const gate = new Promise<void>((resolve) => {
    release = resolve
  })
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname.startsWith('/api/images/')) {
      if (url.pathname.endsWith('frame-6.png')) await gate
      await route.fulfill({ contentType: 'image/png', body: png })
    } else if (url.pathname === '/api/observations')
      await route.fulfill({ json: { observations: frames } })
    else await route.fulfill({ json: {} })
  })
  await page.goto('/?ra=133.7&dec=-7.2&fov=10')
  await page
    .locator('.sky-image')
    .evaluate((image: HTMLImageElement) => image.decode())
  await page
    .getByRole('button', { name: 'Play observations', exact: true })
    .click()
  await expect(page).toHaveURL(new RegExp('obs=' + frames[6].id.split('.')[1]))
  await page.waitForTimeout(1400)
  await expect(page).toHaveURL(new RegExp('obs=' + frames[6].id.split('.')[1]))
  release()
  await expect(page).toHaveURL(new RegExp('obs=' + frames[0].id.split('.')[1]))
})

test('transient image failures retry the same exposure', async ({ page }) => {
  const requests: string[] = []
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname.startsWith('/api/images/')) {
      if (url.pathname.endsWith('frame-0.png')) {
        requests.push(url.search)
        if (requests.length <= 2) {
          await route.fulfill({ status: 503, body: 'Temporary outage' })
          return
        }
      }
      await route.fulfill({ contentType: 'image/png', body: png })
    } else if (url.pathname === '/api/observations')
      await route.fulfill({ json: { observations: frames } })
    else await route.fulfill({ json: {} })
  })
  await page.goto('/?ra=133.7&dec=-7.2&fov=10')
  await expect
    .poll(
      async () =>
        page
          .locator('.sky-image')
          .evaluateAll((images: HTMLImageElement[]) =>
            images.some((image) => image.complete && image.naturalWidth > 0),
          ),
      { timeout: 12000 },
    )
    .toBe(true)
  expect(requests).toEqual(['', '?retry=1', '?retry=2'])
  await expect(
    page.getByText('Unable to display image', { exact: true }),
  ).toHaveCount(0)
})
