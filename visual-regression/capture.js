const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.BROWSER_PATH || undefined,
  });
  const page = await browser.newPage({
    viewport: { width: 1536, height: 1024 },
    deviceScaleFactor: 1,
  });
  await page.goto(process.env.VIRALIZER_URL || 'http://127.0.0.1:8000/', {
    waitUntil: 'networkidle',
  });
  if (page.url().includes('/login')) {
    await page.locator('#password').fill(process.env.APP_PASSWORD || '');
    await Promise.all([
      page.waitForNavigation({ waitUntil: 'networkidle' }),
      page.locator('button[type="submit"]').click(),
    ]);
  }
  await page.waitForTimeout(4000);
  await page.screenshot({ path: process.env.SCREENSHOT_PATH || 'current.png' });
  await browser.close();
})();
