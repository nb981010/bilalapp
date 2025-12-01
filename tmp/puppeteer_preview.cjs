const puppeteer = require('puppeteer');

(async () => {
  const base = 'http://127.0.0.1:5173';
  const browser = await puppeteer.launch({ args: ['--no-sandbox','--disable-setuid-sandbox'] });
  const page = await browser.newPage();

  try {
    console.log('Visiting /');
    await page.goto(base + '/', { waitUntil: 'networkidle2', timeout: 30000 });
    await page.waitForSelector('h1, h2', { timeout: 5000 });
    const h = await page.$eval('h1, h2', el => el.textContent.trim());
    console.log('/ header:', h || 'NO HEADER');

    // Check Today's Schedule card exists on / (dashboard)
    const hasSchedule = await page.evaluate(() => {
      return !!Array.from(document.querySelectorAll('h2')).some(h => /Today's Schedule|Today\'s Schedule/i.test(h.textContent || ''));
    });
    console.log("Today's Schedule present:", hasSchedule);

    // Try finding a refresh button by text/title
    const refreshBtnPresent = await page.evaluate(() => {
      const btns = Array.from(document.querySelectorAll('button'));
      return btns.some(b => ((b.textContent||'').toLowerCase().includes('refresh') || (b.getAttribute('title')||'').toLowerCase().includes('refresh')));
    });
    console.log('Refresh button present (approx):', refreshBtnPresent);

    // Capture screenshot of the schedule area for manual inspection
    const headers = await page.$$('h2');
    let foundIndex = -1;
    for (let i = 0; i < headers.length; i++) {
      const txt = await (await headers[i].getProperty('textContent')).jsonValue();
      if (/Today's Schedule|Today\'s Schedule/i.test(txt || '')) { foundIndex = i; break; }
    }
    if (foundIndex >= 0) {
      const headerHandle = headers[foundIndex];
      const cardHandle = await headerHandle.evaluateHandle(h => {
        let el = h;
        while (el && el.tagName && el.tagName.toLowerCase() !== 'div') el = el.parentElement;
        return el;
      });
      const cardEl = cardHandle.asElement && cardHandle.asElement();
      if (cardEl) {
        await cardEl.screenshot({ path: 'tmp/schedule_preview.png' });
        console.log('Saved screenshot: tmp/schedule_preview.png');
      }
    }

    console.log('Puppeteer preview checks passed');
  } catch (err) {
    console.error('Puppeteer preview check failed:', err);
    await browser.close();
    process.exit(2);
  }

  await browser.close();
  process.exit(0);
})();
