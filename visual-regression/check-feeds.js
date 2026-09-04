const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.BROWSER_PATH });
  const page = await browser.newPage({ viewport: { width: 1536, height: 1024 } });
  const sample = label => ({ topics: [{ topic: `${label} result`, category: label, thumbnail_url: '/static/final/thumbnails/table-iphone.png' }] });
  await page.route('**/api/**', async route => {
    const url = route.request().url();
    const label = url.includes('/daily/latest') ? 'Hot Topics' : url.includes('/regional/') ? 'Saudi & Arabic Topics' : url.includes('/betting/') ? 'Betting Topics' : url.includes('/ideas/') ? 'Idea Smith' : url.includes('/category/') ? 'Topic Intelligence' : 'Viralizer Topics';
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(sample(label)) });
  });
  await page.goto(process.env.VIRALIZER_URL || 'http://127.0.0.1:8000/', { waitUntil: 'domcontentloaded' });
  if (page.url().includes('/login')) {
    await page.locator('#password').fill(process.env.APP_PASSWORD || '');
    await Promise.all([page.waitForNavigation(), page.locator('button[type="submit"]').click()]);
  }
  const labels = ['Viralizer Topics', 'Hot Topics', 'Topic Intelligence', 'Idea Smith', 'Saudi & Arabic Topics', 'Betting Topics'];
  const results = [];
  const feeds = ['viralizer', 'hot', 'topic-intelligence', 'idea-smith', 'saudi', 'betting'];
  for (let index = 0; index < labels.length; index++) {
    const label = labels[index];
    await page.locator(`.tab[data-feed="${feeds[index]}"]`).click();
    await page.waitForFunction(text => document.querySelector('#runStatus')?.textContent.includes('ready'), label);
    results.push({ label, row: await page.locator('#topicRows .topic-name').first().textContent(), image: await page.locator('#topicRows img').first().getAttribute('src') });
  }
  for (const label of ['Discover', 'Topic Intelligence', 'Idea Smith']) {
    await page.locator('.side .nav a').filter({ hasText: label }).click();
    await page.waitForFunction(() => document.querySelector('#runStatus')?.textContent.includes('ready'));
    results.push({ sidebar: label, active: await page.locator('.tab.active').textContent(), row: await page.locator('#topicRows .topic-name').first().textContent() });
  }
  const destinations = await page.locator('.side .nav a').evaluateAll(links => Object.fromEntries(links.map(link => [link.textContent.trim(), link.getAttribute('href')])));
  results.push({ destinations });
  console.log(JSON.stringify(results, null, 2));
  await browser.close();
})();
