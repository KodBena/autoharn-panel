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

  // Click "show raw row"
  await page.click('button:has-text("show raw row")');
  await page.waitForTimeout(500);
  await page.screenshot({ path: `${DIR}/item-show-raw-row.png` });

  // Click "co-sign this row" and observe
  const cosignBtn = page.locator('button:has-text("co-sign this row")');
  const isDisabled = await cosignBtn.isDisabled();
  console.log('co-sign button disabled attr?', isDisabled);
  await cosignBtn.click({ force: true }).catch(e => console.log('click error', e.message));
  await page.waitForTimeout(1000);
  await page.screenshot({ path: `${DIR}/item-cosign-clicked.png` });
  const bodyText = await page.evaluate(() => document.body.innerText);
  console.log('Body text after cosign click (last 400 chars of relevant area):', bodyText.slice(0, 1500));

  await browser.close();
})();
