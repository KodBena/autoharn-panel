const { chromium } = require('playwright');

const BASE = 'http://192.168.122.68:8420';
const DIR = '/tmp/claude-1000/-home-bork-w-vdc-1-experience-autoharn-panel/889df121-8ea9-49ca-a224-bad131076799/scratchpad/audit';

(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1400, height: 900 } });
  const page = await context.newPage();

  const consoleMsgs = [];
  const pageErrors = [];
  const badResponses = [];

  page.on('console', msg => {
    if (msg.type() === 'error' || msg.type() === 'warning') {
      consoleMsgs.push(`[${msg.type()}] ${msg.text()}`);
    }
  });
  page.on('pageerror', err => pageErrors.push(err.message));
  page.on('response', res => {
    if (res.status() >= 400) {
      badResponses.push(`${res.status()} ${res.url()}`);
    }
  });

  console.log('Navigating to home...');
  await page.goto(BASE, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForTimeout(3000);
  await page.screenshot({ path: `${DIR}/01-home.png`, fullPage: true });

  const title = await page.title();
  console.log('Title:', title);

  // Dump nav links
  const links = await page.evaluate(() => {
    return Array.from(document.querySelectorAll('a, [role=link], nav *')).map(a => ({
      tag: a.tagName, text: a.textContent.trim().slice(0,60), href: a.getAttribute('href')
    })).filter(x => x.text);
  });
  console.log('LINKS:', JSON.stringify(links.slice(0, 50), null, 2));

  const bodyText = await page.evaluate(() => document.body.innerText.slice(0, 3000));
  console.log('BODY TEXT SNIPPET:\n', bodyText);

  console.log('CONSOLE MSGS:', JSON.stringify(consoleMsgs));
  console.log('PAGE ERRORS:', JSON.stringify(pageErrors));
  console.log('BAD RESPONSES:', JSON.stringify(badResponses));

  await browser.close();
})();
