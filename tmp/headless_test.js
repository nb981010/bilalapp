const puppeteer = require('puppeteer');

(async () => {
  const browser = await puppeteer.launch({args:['--no-sandbox','--disable-setuid-sandbox']});
  const page = await browser.newPage();
  const logs = [];
  const responses = [];

  page.on('console', msg => {
    try { logs.push({type: 'console', text: msg.text(), location: msg.location()}); } catch(e) { logs.push({type:'console', text: String(msg)}); }
  });
  page.on('pageerror', err => logs.push({type: 'pageerror', message: err.message, stack: err.stack}));
  page.on('requestfailed', req => logs.push({type: 'requestfailed', url: req.url(), err: req.failure() ? req.failure().errorText : null}));

  page.on('response', async res => {
    try {
      const url = res.url();
      const status = res.status();
      const ct = (res.headers() || {})['content-type'] || '';
      // capture main app bundle and any script responses
      if (url.includes('/assets/') || ct.includes('javascript')) {
        let text = '';
        try { text = await res.text(); } catch(e) { text = `<unable to read response: ${e.message}>`; }
        responses.push({url, status, contentType: ct, length: typeof text === 'string' ? text.length : null, preview: typeof text === 'string' ? text.slice(0,1000) : null});
      }
    } catch (e) {
      // ignore
    }
  });

  try {
    console.log('Navigating to http://127.0.0.1:3000/');
    await page.goto('http://127.0.0.1:3000/', {waitUntil: 'networkidle2', timeout: 30000});
    // give some time for runtime errors to surface
    await page.waitForTimeout(1500);
  } catch (e) {
    logs.push({type: 'navigationerror', message: e.message});
  }

  console.log('\n--- CONSOLE LOGS ---');
  console.log(JSON.stringify(logs, null, 2));

  console.log('\n--- RESPONSES (filtered) ---');
  console.log(JSON.stringify(responses, null, 2));

  await browser.close();
  process.exit(0);
})().catch(err => {
  console.error('SCRIPT ERROR', err);
  process.exit(2);
});
