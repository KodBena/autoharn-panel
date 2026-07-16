const { chromium } = require('playwright');

const BASE = 'http://192.168.122.68:8420';
const DIR = '/tmp/claude-1000/-home-bork-w-vdc-1-experience-autoharn-panel/889df121-8ea9-49ca-a224-bad131076799/scratchpad/audit';

(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1400, height: 900 } });
  const page = await context.newPage();

  const apiCalls = [];
  page.on('request', req => {
    if (req.url().includes('/api/')) apiCalls.push(req.method() + ' ' + req.url());
  });
  page.on('response', async res => {
    if (res.url().includes('/api/') && res.url().includes('commission')) {
      let body = '';
      try { body = (await res.text()).slice(0, 500); } catch(e) {}
      console.log('COMMISSION API RESP', res.status(), res.url(), '\n  body:', body);
    }
  });

  await page.goto(BASE, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForTimeout(1500);
  await page.click('button:has-text("Commission decomposition")');
  await page.waitForTimeout(1000);
  await page.selectOption('select', { index: 8 }); // #216
  await page.waitForTimeout(1000);

  console.log('All API calls so far:', JSON.stringify(apiCalls, null, 2));

  // Now test client-side navigation to an item view via row citation link
  await page.click('button:has-text("Recent ledger")');
  await page.waitForTimeout(1000);
  const firstCitation = page.locator('a[href^="/item/"]').first();
  const href = await firstCitation.getAttribute('href');
  console.log('Clicking citation link:', href);
  await firstCitation.click();
  await page.waitForTimeout(1200);
  console.log('URL after client-side click:', page.url());
  await page.screenshot({ path: `${DIR}/item-view-clientside.png`, fullPage: true });
  const bodyText = await page.evaluate(() => document.body.innerText);
  console.log('Item view body text (clientside nav):', bodyText.slice(0, 800));

  // Now reload same URL (hard nav) to see if it breaks
  const currentUrl = page.url();
  console.log('Reloading (hard nav) at', currentUrl);
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1500);
  const bodyText2 = await page.evaluate(() => document.body.innerText);
  console.log('Body text after reload:', bodyText2.slice(0, 800));
  await page.screenshot({ path: `${DIR}/item-view-after-reload.png`, fullPage: true });

  await browser.close();
})();
