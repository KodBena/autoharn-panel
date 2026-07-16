const { chromium } = require('playwright');

const BASE = 'http://192.168.122.68:8420';
const DIR = '/tmp/claude-1000/-home-bork-w-vdc-1-experience-autoharn-panel/889df121-8ea9-49ca-a224-bad131076799/scratchpad/audit';

(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1400, height: 900 } });
  const page = await context.newPage();
  page.on('console', msg => { if (msg.type()==='error') console.log('[CONSOLE error]', msg.text()); });
  page.on('response', res => { if (res.status()>=400) console.log('[BADRESP]', res.status(), res.url()); });

  await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1500);
  await page.click('button:has-text("Recent ledger")');
  await page.waitForTimeout(800);
  await page.click('a[href="/item/183"]');
  await page.waitForTimeout(1200);
  await page.click('button:has-text("co-sign this row")');
  await page.waitForTimeout(500);

  await page.fill('input[placeholder="basis statement (why you are co-signing)"]', 'Playwright audit test - expect refusal (read-only)');
  await page.click('button:has-text("submit")');
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${DIR}/item-cosign-submit-result.png`, fullPage: true });
  const bodyText = await page.evaluate(() => document.body.innerText);
  console.log('Body after submit attempt:\n', bodyText.slice(bodyText.indexOf('Obligations'), bodyText.indexOf('Obligations')+1200));

  await browser.close();
})();
