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

  // 1. Home viewport screenshot
  await page.screenshot({ path: `${DIR}/home-viewport.png` });

  // Click Recent ledger tab
  await page.click('button:has-text("Recent ledger")');
  await page.waitForTimeout(1000);
  await page.screenshot({ path: `${DIR}/recent-ledger-viewport.png` });

  // Inspect the read-only lock badge tooltip
  const lockBadge = await page.locator('text=read-only (locked)').first();
  if (await lockBadge.count()) {
    await lockBadge.hover();
    await page.waitForTimeout(500);
    await page.screenshot({ path: `${DIR}/lock-badge-hover.png` });
    const title = await lockBadge.getAttribute('title');
    console.log('Lock badge title attr:', title);
  }

  // Inspect SSE indicator
  const sseBadge = await page.locator('text=live (SSE)').first();
  if (await sseBadge.count()) {
    await sseBadge.hover();
    await page.waitForTimeout(300);
    console.log('SSE badge title attr:', await sseBadge.getAttribute('title'));
  }

  // Try kind filter dropdown
  const kindSelect = page.locator('select').first();
  const selectCount = await page.locator('select').count();
  console.log('Number of <select> elements on Recent ledger:', selectCount);

  // Try setting kind filter to "work_opened"
  try {
    await page.selectOption('select >> nth=0', { label: 'work_opened' });
    await page.waitForTimeout(800);
    await page.screenshot({ path: `${DIR}/recent-ledger-filter-work_opened.png` });
    const rowCount = await page.locator('table tbody tr').count();
    console.log('Rows after filtering kind=work_opened:', rowCount);
  } catch (e) {
    console.log('kind filter select failed:', e.message);
  }

  // reset kind filter
  try {
    await page.selectOption('select >> nth=0', { label: '(any)' });
    await page.waitForTimeout(500);
  } catch (e) {}

  // Try actor filter (text input?) - check DOM
  const actorInputs = await page.evaluate(() => {
    return Array.from(document.querySelectorAll('input')).map(i => ({type: i.type, placeholder: i.placeholder, name: i.name}));
  });
  console.log('Inputs found:', JSON.stringify(actorInputs));

  // Try sort toggle - click on ID header
  const idHeader = page.locator('text=ID').first();
  if (await idHeader.count()) {
    await idHeader.click();
    await page.waitForTimeout(600);
    await page.screenshot({ path: `${DIR}/recent-ledger-sort-toggle.png` });
    const firstRowIdAfter = await page.locator('table tbody tr').first().innerText();
    console.log('First row after sort click:', firstRowIdAfter.slice(0,80));
  }

  // Pagination: find pagination controls
  const bodyTextAfterSort = await page.evaluate(() => document.body.innerText);
  console.log('Contains "Next"?', bodyTextAfterSort.includes('Next'));
  console.log('Contains "Page"?', bodyTextAfterSort.includes('Page') || bodyTextAfterSort.includes('page'));

  await browser.close();
})();
