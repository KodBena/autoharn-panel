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
  await page.waitForTimeout(1500);

  // --- Commission decomposition: try each option in dropdown ---
  await page.click('button:has-text("Commission decomposition")');
  await page.waitForTimeout(800);
  const options = await page.locator('select').first().locator('option').allTextContents();
  console.log('Commission dropdown options:', JSON.stringify(options));

  for (let i = 0; i < options.length; i++) {
    await page.selectOption('select', { index: i });
    await page.waitForTimeout(700);
    const bodyText = await page.evaluate(() => document.body.innerText);
    const noItemsLine = bodyText.includes('No decomposition items authored');
    console.log(`Option ${i} ("${options[i].slice(0,40)}"): noItemsMsg=${noItemsLine}`);
    if (!noItemsLine && i < 5) {
      await page.screenshot({ path: `${DIR}/commission-decomp-option${i}.png`, fullPage: true });
    }
  }

  // pick option with real items -> screenshot regardless for a couple non-empty ones
  for (let i = 0; i < options.length; i++) {
    await page.selectOption('select', { index: i });
    await page.waitForTimeout(700);
    const bodyText = await page.evaluate(() => document.body.innerText);
    if (!bodyText.includes('No decomposition items authored')) {
      await page.screenshot({ path: `${DIR}/commission-decomp-nonempty-${i}.png`, fullPage: true });
      break;
    }
  }

  // --- Item detail view ---
  await page.goto(`${BASE}/item/247`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${DIR}/item-247.png`, fullPage: true });

  // --- Glossary/tooltip mechanism: look for jargon like s33, ADR, ADR-0017 ---
  const jargonEls = await page.evaluate(() => {
    const all = Array.from(document.querySelectorAll('*'));
    const matches = [];
    for (const el of all) {
      if (el.children.length === 0 && el.textContent && /\bs\d{2,3}\b|ADR-?\d{4}/.test(el.textContent)) {
        matches.push({tag: el.tagName, cls: el.className, text: el.textContent.trim().slice(0,80), title: el.getAttribute('title')});
      }
    }
    return matches.slice(0, 20);
  });
  console.log('Jargon elements on item/247:', JSON.stringify(jargonEls, null, 2));

  // --- Invalid route ---
  await page.goto(`${BASE}/item/9999999`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${DIR}/item-invalid-id.png`, fullPage: true });
  console.log('Invalid item body text:', (await page.evaluate(() => document.body.innerText)).slice(0, 500));

  await page.goto(`${BASE}/totally/bogus/route`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${DIR}/bogus-route.png`, fullPage: true });
  console.log('Bogus route body text:', (await page.evaluate(() => document.body.innerText)).slice(0, 500));

  await browser.close();
})();
