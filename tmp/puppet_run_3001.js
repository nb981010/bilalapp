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

    // Check for Today's Schedule card and Refresh button
    const hasSchedule = await page.evaluate(() => !!document.querySelector('div') && /Today\'s Schedule/i.test(document.body.innerText));
    console.log("Has Today's Schedule text:", hasSchedule);

    const refreshBtn = await page.$x("//button[contains(., 'Refresh') or contains(., 'Refreshing')]");
    console.log('Refresh button present:', refreshBtn.length > 0);

    // Capture screenshot
    await page.screenshot({ path: 'tmp/schedule_capture.png', fullPage: false });
    console.log('Screenshot saved to tmp/schedule_capture.png');

    console.log('Puppeteer run completed successfully.');
  } catch (err) {
    console.error('Puppeteer run failed:', err);
    await browser.close();
    process.exit(2);
  }

  await browser.close();
  process.exit(0);
})();
