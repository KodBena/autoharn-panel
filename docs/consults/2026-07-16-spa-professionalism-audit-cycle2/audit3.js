const { chromium } = require('playwright');

const BASE = 'http://192.168.122.68:8420';
const DIR = '/tmp/claude-1000/-home-bork-w-vdc-1-experience-autoharn-panel/889df121-8ea9-49ca-a224-bad131076799/scratchpad/audit';

function attachLogging(page, tag) {
  page.on('console', msg => {
    if (msg.type() === 'error' || msg.type() === 'warning') {
      console.log(`[CONSOLE ${tag}][${msg.type()}]`, msg.text());
    }
  });
  page.on('pageerror', err => console.log(`[PAGEERROR ${tag}]`, err.message));
  page.on('response', res => {
    if (res.status() >= 400) console.log(`[BADRESP ${tag}]`, res.status(), res.url());
  });
}

(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1400, height: 900 } });
  const page = await context.newPage();
  attachLogging(page, 'main');

  await page.goto(BASE, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForTimeout(2000);

  // Measure scrollHeight of recent ledger with default limit
  await page.click('button:has-text("Recent ledger")');
  await page.waitForTimeout(1000);
  const rowCount = await page.locator('table tbody tr').count();
  const scrollHeight = await page.evaluate(() => document.body.scrollHeight);
  console.log(`Recent ledger: ${rowCount} rows rendered, page scrollHeight=${scrollHeight}px`);

  // Check for pagination controls text/buttons
  const paginationText = await page.evaluate(() => {
    const els = Array.from(document.querySelectorAll('button, a, span, div')).filter(e => /next|prev|page \d|of \d+ page/i.test(e.textContent) && e.children.length === 0);
    return els.map(e => e.textContent.trim()).slice(0, 20);
  });
  console.log('Pagination-related small elements:', JSON.stringify(paginationText));

  // ---- Profiles tab ----
  await page.click('button:has-text("Profiles")');
  await page.waitForTimeout(1000);
  await page.screenshot({ path: `${DIR}/profiles-tab.png`, fullPage: true });

  // ---- Commission decomposition tab ----
  await page.click('button:has-text("Commission decomposition")');
  await page.waitForTimeout(1200);
  await page.screenshot({ path: `${DIR}/commission-decomp-tab.png`, fullPage: true });
  const commissionSelectCount = await page.locator('select').count();
  console.log('Commission decomposition select count:', commissionSelectCount);

  // ---- Work items tab ----
  await page.click('button:has-text("Work items")');
  await page.waitForTimeout(1200);
  await page.screenshot({ path: `${DIR}/work-items-tab.png`, fullPage: true });

  // ---- Review gap tab ----
  await page.click('button:has-text("Review gap")');
  await page.waitForTimeout(1200);
  await page.screenshot({ path: `${DIR}/review-gap-tab.png`, fullPage: true });

  // ---- Questions tab ----
  await page.click('button:has-text("Questions")');
  await page.waitForTimeout(1200);
  await page.screenshot({ path: `${DIR}/questions-tab.png`, fullPage: true });

  await browser.close();
})();
