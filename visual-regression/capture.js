const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.BROWSER_PATH || undefined,
  });
  const page = await browser.newPage({
    viewport: {
      width: Number(process.env.VIEWPORT_WIDTH || 1536),
      height: Number(process.env.VIEWPORT_HEIGHT || 1024),
    },
    deviceScaleFactor: 1,
  });
  const targetUrl = process.env.VIRALIZER_URL || 'http://127.0.0.1:8000/';
  await page.goto(targetUrl, {
    waitUntil: 'networkidle',
  });
  if (page.url().includes('/login')) {
    await page.locator('#password').fill(process.env.APP_PASSWORD || '');
    await Promise.all([
      page.waitForNavigation({ waitUntil: 'networkidle' }),
      page.locator('button[type="submit"]').click(),
    ]);
    if (new URL(page.url()).pathname !== new URL(targetUrl).pathname || new URL(targetUrl).hash) {
      await page.goto(targetUrl, { waitUntil: 'networkidle' });
    }
  }
  await page.waitForTimeout(4000);
  await page.screenshot({ path: process.env.SCREENSHOT_PATH || 'current.png' });
  await browser.close();
})();
