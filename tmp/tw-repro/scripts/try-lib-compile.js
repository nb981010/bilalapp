const path = require('path');
const lib = require(path.resolve(__dirname, '..', 'node_modules', 'tailwindcss', 'dist', 'lib.js'));
const fs = require('fs');

async function run() {
  const config = require(path.resolve(__dirname, '..', 'tailwind.config.cjs'));
  const css = '@tailwind utilities';
  try {
    const res = await lib.compile(css, { config });
    if (res && res.css) {
      fs.writeFileSync(path.resolve(__dirname, '..', 'out-lib.css'), res.css, 'utf8');
      console.log('Wrote out-lib.css, length:', res.css.length);
    } else {
      console.log('No css in result:', res);
    }
  } catch (e) {
    console.error('compile error:', e && e.stack ? e.stack : e);
  }
}
run();
