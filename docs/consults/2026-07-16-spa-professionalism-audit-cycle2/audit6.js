const { chromium } = require('playwright');

const BASE = 'http://192.168.122.68:8420';
const DIR = '/tmp/claude-1000/-home-bork-w-vdc-1-experience-autoharn-panel/889df121-8ea9-49ca-a224-bad131076799/scratchpad/audit';

(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1400, height: 900 } });
  const page = await context.newPage();

  await page.goto(BASE, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForTimeout(1500);

  // Screenshot commission decomposition for #247 as visual evidence
  await page.click('button:has-text("Commission decomposition")');
  await page.waitForTimeout(800);
  const options = await page.locator('select').first().locator('option').allTextContents();
  const idx247 = options.findIndex(o => o.includes('#247'));
  await page.selectOption('select', { index: idx247 });
  await page.waitForTimeout(1000);
  await page.screenshot({ path: `${DIR}/commission-247-zero-items-BUG.png`, fullPage: true });

  // Check work items tab for ADR-0017 / ADR-0005 jargon tooltip mechanism
  await page.click('button:has-text("Work items")');
  await page.waitForTimeout(1000);
  const adrEl = page.locator('text=ADR-0017').first();
  if (await adrEl.count()) {
    const html = await adrEl.evaluate(el => el.outerHTML);
    console.log('ADR-0017 element HTML:', html.slice(0, 300));
    await adrEl.hover();
    await page.waitForTimeout(500);
    await page.screenshot({ path: `${DIR}/adr-hover.png` });
  } else {
    console.log('No ADR-0017 text found on Work items tab');
  }

  // Check for kind glossary in recent ledger - hover over "kind" column value like "work_opened" or dropdown option tooltips
  await page.click('button:has-text("Recent ledger")');
  await page.waitForTimeout(800);
  const kindCellEl = page.locator('td:has-text("work_opened")').first();
  if (await kindCellEl.count()) {
    console.log('kind cell title attr:', await kindCellEl.getAttribute('title'));
    const kindSpan = kindCellEl.locator('*').first();
    console.log('kind cell HTML:', await kindCellEl.evaluate(el => el.outerHTML).catch(()=>'n/a'));
  }
  // Look for any element with a "glossary" class/data attribute
  const glossaryEls = await page.evaluate(() => {
    return Array.from(document.querySelectorAll('[data-glossary], .glossary, [class*="gloss"], abbr, [title]')).length;
  });
  console.log('Elements with glossary-ish markers or [title] attr count:', glossaryEls);

  // Responsive screenshots
  await page.setViewportSize({ width: 600, height: 900 });
  await page.waitForTimeout(500);
  await page.screenshot({ path: `${DIR}/responsive-600px.png`, fullPage: false });

  await page.click('button:has-text("Commission decomposition")').catch(()=>{});
  await page.waitForTimeout(500);
  await page.screenshot({ path: `${DIR}/responsive-600px-commission.png`, fullPage: false });

  await page.setViewportSize({ width: 1200, height: 900 });
  await page.waitForTimeout(500);
  await page.screenshot({ path: `${DIR}/responsive-1200px.png`, fullPage: false });

  await browser.close();
})();
