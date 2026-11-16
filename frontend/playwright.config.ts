import { defineConfig } from '@playwright/test'
import path from 'node:path'

export default defineConfig({
  testDir: './tests',
  fullyParallel: true,
  use: {
    baseURL: 'http://127.0.0.1:8011',
    headless: true,
    channel: process.env.CI ? undefined : 'chrome',
  },
  webServer: {
    command:
      'uv run --project ../backend uvicorn spherex_api.app:app --host 127.0.0.1 --port 8011',
    url: 'http://127.0.0.1:8011/health',
    reuseExistingServer: !process.env.CI,
    env: { SPHEREX_DATA_DIR: path.resolve('test-results/api-cache') },
  },
})
