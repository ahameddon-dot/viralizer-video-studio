const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.BROWSER_PATH });
  const page = await browser.newPage({ viewport: { width: 1536, height: 1024 } });
  const base = process.env.VIRALIZER_URL || 'http://127.0.0.1:8001';
  await page.goto(`${base}/studio#studio`, { waitUntil: 'domcontentloaded' });
  if (page.url().includes('/login')) {
    await page.locator('#password').fill(process.env.APP_PASSWORD || '');
    await Promise.all([page.waitForNavigation(), page.locator('button[type="submit"]').click()]);
  }
  const checks = [];
  async function open(hash, selector) {
    await page.goto(`${base}/studio${hash}`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(300);
    checks.push({ hash, visible: await page.locator(selector).isVisible() });
  }
  await open('#hotView', '#hotView');
  await open('#topicIntelligenceView', '#topicIntelligenceView');
  await open('#viralizerView', '#viralizerView');
  await open('#ideaSmithView', '#ideaSmithView');
  await open('#regionalView', '#regionalView');
  await open('#bettingView', '#bettingView');
  await open('#studio', '#creationFormats');
  checks.push({ creationFormats: await page.locator('#creationFormats [data-format]').count() });
  await open('#referenceAssetsPanel', '#referenceAssetsPanel');
  await open('#growthStudioPanel', '#growthStudioPanel');
  checks.push({
    metadata: await page.locator('#metadataPanel').count() === 1,
    thumbnailUpload: await page.locator('#thumbnailUpload').count() === 1,
    generationConfirm: await page.locator('#generationConfirm').count() === 1,
    providerSelector: await page.locator('#videoProvider').count() === 1,
    imageProvider: await page.locator('#imageProvider').count() === 1,
    growthHistory: await page.locator('#growthHistory').count() === 1,
  });
  console.log(JSON.stringify(checks, null, 2));
  if (checks.some(item => item.visible === false) || checks.find(item => item.creationFormats)?.creationFormats !== 7) process.exitCode = 1;
  await browser.close();
})();
