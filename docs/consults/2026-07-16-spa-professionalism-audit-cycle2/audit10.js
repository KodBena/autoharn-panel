const { chromium } = require('playwright');
const BASE = 'http://192.168.122.68:8420';
(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  await page.goto(BASE, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1500);
  const html = await page.content();
  console.log('Contains "new data"?', /new data/i.test(html));
  console.log('Contains "EventSource"?', /EventSource/i.test(html));
  // check network resource type for /api/events
  const resourceType = await page.evaluate(async () => {
    const res = await fetch('/api/events');
    return res.headers.get('content-type');
  });
  console.log('/api/events content-type:', resourceType);
  await browser.close();
})();
