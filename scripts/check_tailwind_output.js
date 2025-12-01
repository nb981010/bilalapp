const fs = require('fs');
const path = require('path');
const postcss = require('postcss');
const plugins = [ require('@tailwindcss/postcss'), require('autoprefixer') ];
(async ()=>{
  try{
    const infile = path.resolve(__dirname, '..', 'src', 'index.css');
    const css = fs.readFileSync(infile, 'utf8');
    const result = await postcss(plugins).process(css, { from: infile });
    console.log(result.css);
  }catch(err){
    console.error('ERROR:', err && err.stack || err);
    process.exit(1);
  }
})();
