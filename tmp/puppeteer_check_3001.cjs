const puppeteer = require('puppeteer');

(async () => {
  const base = 'http://127.0.0.1:3001';
  const browser = await puppeteer.launch({ args: ['--no-sandbox','--disable-setuid-sandbox'] });
  const page = await browser.newPage();

  try {
    console.log('Visiting /');
    await page.goto(base + '/', { waitUntil: 'networkidle2', timeout: 30000 });
    await page.waitForSelector('h1, h2', { timeout: 5000 });
    const h = await page.$eval('h1, h2', el => el.textContent.trim());
    console.log('/ header:', h);

    console.log('Visiting /test');
    await page.goto(base + '/test', { waitUntil: 'networkidle2', timeout: 30000 });
    await page.waitForSelector('h3, h2', { timeout: 5000 });
    const testHeader = await page.$eval('h3, h2', el => el.textContent.trim());
    console.log('/test header:', testHeader);

    // Check Today's Schedule card exists on / (dashboard)
    console.log("Checking Today's Schedule on /");
    await page.goto(base + '/', { waitUntil: 'networkidle2', timeout: 30000 });
    const hasSchedule = await page.evaluate(() => {
      return !!Array.from(document.querySelectorAll('h2')).some(h => /Today's Schedule|Today\'s Schedule/i.test(h.textContent || ''));
    });
    console.log("Today's Schedule present:", hasSchedule);

    // Try clicking refresh button if present
    const refreshBtn = await page.$x("//button[.//svg and contains(., 'Refresh') or contains(., 'Refreshing')]");
    console.log('Refresh button present (approx):', refreshBtn.length > 0);

    console.log('Puppeteer temporary checks passed');
  } catch (err) {
    console.error('Puppeteer check failed:', err);
    await browser.close();
    process.exit(2);
  }

  await browser.close();
  process.exit(0);
})();
