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

test('unknown fields open the atlas and all tool tabs remain accessible during outages', async ({
  page,
}) => {
  await page.route('**/atlas.html', (route) =>
    route.fulfill({
      contentType: 'text/html',
      body: '<html><body>Atlas test fixture<script>parent.postMessage({type:"atlas-ready"},location.origin)</script></body></html>',
    }),
  )
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/availability')
      await route.fulfill({
        json: {
          discoveryAvailable: false,
          checkedAt: '2026-11-15T00:00:00Z',
          savedFields: [
            {
              name: 'Saved field',
              raDeg: 133.7,
              decDeg: -7.2,
              fovArcmin: 10,
              detectors: [6],
            },
          ],
        },
      })
    else if (url.pathname === '/api/observations')
      await route.fulfill({
        json:
          url.searchParams.get('ra') === '133.7'
            ? { observations: frames }
            : {
                observations: [],
                fallback: 'atlas',
                discoveryAvailable: false,
                warnings: ['Dated observations unavailable'],
              },
      })
    else if (url.pathname.startsWith('/api/images/'))
      await route.fulfill({ contentType: 'image/png', body: png })
    else if (url.pathname === '/api/science/channels')
      await route.fulfill({
        json: { channels: [{ index: 86, detector: 6, WAVELENGTH: 4.435 }] },
      })
    else await route.fulfill({ json: { samples: [], fluxUnit: 'MJy/sr' } })
  })
  await page.goto('/?ra=17&dec=6&fov=10')
  await expect(page.getByTitle('Real SPHEREx infrared sky atlas')).toBeVisible()
  await expect(
    page.getByText('Live dated-image discovery is unavailable.', {
      exact: false,
    }),
  ).toBeVisible()
  await expect(
    page.getByRole('button', { name: 'Refresh archive', exact: true }),
  ).toHaveCount(0)
  await expect(
    page.getByRole('button', {
      name: 'Highlight candidate changes',
      exact: true,
    }),
  ).toHaveCount(0)
  await expect(
    page.getByRole('button', { name: 'Image processing', exact: true }),
  ).toHaveCount(0)
  await expect(
    page.getByRole('radio', { name: 'Detector (1–6)', exact: true }),
  ).toHaveCount(0)
  await expect(
    page.getByRole('navigation', { name: 'Main navigation' }).getByRole('button'),
  ).toHaveCount(9)
  for (const name of ['Motion', 'Discover', 'Spectrum', 'Compare']) {
    await page.getByRole('button', { name, exact: true }).click()
    await expect(page.getByRole('button', { name, exact: true })).toHaveAttribute(
      'aria-current',
      'page',
    )
    await expect(page.getByText('Dated observations required', { exact: true })).toBeVisible()
  }
  await page.reload()
  await expect(page.getByRole('button', { name: 'Compare', exact: true })).toHaveAttribute(
    'aria-current',
    'page',
  )
  await expect(page.getByText('Dated observations required', { exact: true })).toBeVisible()
  await page.getByLabel('Saved observation fields').selectOption('0')
  await expect(page.locator('.sky-image')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Compare', exact: true })).toHaveAttribute(
    'aria-current',
    'page',
  )
  await expect(page.getByText('Dated observations required', { exact: true })).toHaveCount(0)
  await page.getByLabel('Right ascension (RA)', { exact: true }).fill('17')
  await page.getByLabel('Declination (Dec)', { exact: true }).fill('6')
  await page.getByRole('button', { name: 'Explore sky', exact: true }).click()
  await expect(page.getByTitle('Real SPHEREx infrared sky atlas')).toBeVisible()
  await page.getByRole('button', { name: 'Motion', exact: true }).click()
  await page.getByRole('button', { name: 'Open guided targets', exact: true }).click()
  await expect(page.getByRole('button', { name: /Barnard's Star/ })).toBeVisible()
  await page.getByLabel('Saved observation fields').selectOption('0')
  await expect(page.locator('.sky-image')).toBeVisible()
  await expect(
    page.getByRole('button', {
      name: 'Highlight candidate changes',
      exact: true,
    }),
  ).toBeVisible()
  await expect(
    page.getByRole('button', { name: 'Refresh archive', exact: true }),
  ).toHaveCount(0)
  await page.getByRole('button', { name: 'Science', exact: true }).click()
  await expect(
    page.getByRole('button', {
      name: 'Extract six-detector spectrum',
      exact: true,
    }),
  ).toHaveCount(0)
  await page.getByRole('button', { name: 'Light curves', exact: true }).click()
  await expect(
    page.getByRole('button', { name: 'Measure light curve', exact: true }),
  ).toBeVisible()
})

test('highlight candidate changes explicitly starts the comparison analysis', async ({
  page,
}) => {
  let requested = ''
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/availability')
      await route.fulfill({
        json: {
          discoveryAvailable: true,
          checkedAt: '2026-11-15T00:00:00Z',
          savedFields: [],
        },
      })
    else if (url.pathname === '/api/observations')
      await route.fulfill({ json: { observations: frames } })
    else if (url.pathname.startsWith('/api/images/'))
      await route.fulfill({ contentType: 'image/png', body: png })
    else if (url.pathname === '/api/science/jobs') {
      requested = route.request().postDataJSON().kind
      await route.fulfill({
        json: {
          id: 'comparison',
          subscription: 'test',
          state: 'complete',
          result: {
            candidates: [],
            warnings: [],
            method: 'Comparison fixture',
            provenance: {},
          },
          error: null,
        },
      })
    } else await route.fulfill({ json: {} })
  })
  await page.goto('/?ra=133.7&dec=-7.2&fov=10')
  await page
    .getByRole('button', { name: 'Highlight candidate changes', exact: true })
    .click()
  await expect(
    page.getByText('No candidates returned.', { exact: true }),
  ).toBeVisible()
  expect(requested).toBe('discover')
})
