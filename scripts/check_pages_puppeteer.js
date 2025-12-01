const puppeteer = require('puppeteer');

(async () => {
  const base = 'http://127.0.0.1:3000';
  const browser = await puppeteer.launch({ args: ['--no-sandbox','--disable-setuid-sandbox'] });
  const page = await browser.newPage();

  try {
    // Check settings page
    console.log('Visiting /settings');
    await page.goto(base + '/settings', { waitUntil: 'networkidle2', timeout: 30000 });
    // Wait for heading
    await page.waitForSelector('h3, h2', { timeout: 5000 });
    const settingsHeader = await page.$eval('h3, h2', el => el.textContent.trim());
    console.log('/settings header:', settingsHeader);

    // Check for Sonos toggle presence
    const sonosToggle = await page.$x("//div[contains(., 'Sonos')]");
    console.log('/settings has Sonos block:', sonosToggle.length > 0);

    // Check Test page
    console.log('Visiting /test');
    await page.goto(base + '/test', { waitUntil: 'networkidle2', timeout: 30000 });
    await page.waitForSelector('h3, h2', { timeout: 5000 });
    const testHeader = await page.$eval('h3, h2', el => el.textContent.trim());
    console.log('/test header:', testHeader);

    // Check for Test Controls label
    const hasTestControls = await page.evaluate(() => !!document.querySelector('h3') && /Test Controls/i.test(document.body.innerText));
    console.log('/test has Test Controls text:', hasTestControls);

    console.log('Puppeteer checks passed');
  } catch (err) {
    console.error('Puppeteer check failed:', err);
    await browser.close();
    process.exit(2);
  }

  await browser.close();
  process.exit(0);
})();
