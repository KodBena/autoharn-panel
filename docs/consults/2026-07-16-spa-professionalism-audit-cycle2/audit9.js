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

  // Set actor filter to nonexistent value
  await page.fill('input[placeholder="(any)"]', 'nonexistent_actor_zzz');
  await page.waitForTimeout(1000);
  await page.screenshot({ path: `${DIR}/recent-ledger-actor-empty-result.png` });
  const bodyText = await page.evaluate(() => document.body.innerText);
  console.log('Body text with nonexistent actor filter (should show empty state):', bodyText.slice(bodyText.indexOf('STATEMENT'), bodyText.indexOf('STATEMENT')+300));
  await page.fill('input[placeholder="(any)"]', '');
  await page.waitForTimeout(800);

  // Click Next repeatedly to try to exceed range
  for (let i = 0; i < 3; i++) {
    const nextBtn = page.locator('button:has-text("Next")');
    if (await nextBtn.count() && !(await nextBtn.isDisabled())) {
      await nextBtn.click();
      await page.waitForTimeout(700);
    }
  }
  await page.screenshot({ path: `${DIR}/recent-ledger-paged-forward.png` });
  const pageIndicator = await page.evaluate(() => {
    const el = Array.from(document.querySelectorAll('*')).find(e => /page \d+/i.test(e.textContent) && e.children.length===0);
    return el ? el.textContent : null;
  });
  console.log('Page indicator after clicking Next x3:', pageIndicator);
  const nextDisabled = await page.locator('button:has-text("Next")').isDisabled().catch(()=>null);
  console.log('Next button disabled at this point?', nextDisabled);

  // keep clicking next until disabled or 15 tries
  let tries = 0;
  while (tries < 15) {
    const nextBtn = page.locator('button:has-text("Next")');
    const disabled = await nextBtn.isDisabled().catch(()=>true);
    if (disabled) break;
    await nextBtn.click();
    await page.waitForTimeout(500);
    tries++;
  }
  console.log('Stopped after tries:', tries);
  await page.screenshot({ path: `${DIR}/recent-ledger-last-page.png` });
  const finalIndicator = await page.evaluate(() => {
    const el = Array.from(document.querySelectorAll('*')).find(e => /page \d+/i.test(e.textContent) && e.children.length===0);
    return el ? el.textContent : null;
  });
  console.log('Final page indicator:', finalIndicator);
  const rowCountFinal = await page.locator('table tbody tr').count();
  console.log('Row count on final page:', rowCountFinal);

  await browser.close();
})();
