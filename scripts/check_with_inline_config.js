const fs = require('fs');
const path = require('path');
const postcss = require('postcss');
const tailwindPlugin = require('@tailwindcss/postcss');
const autoprefixer = require('autoprefixer');
(async ()=>{
  try{
    const css = '@tailwind utilities;';
    const abs = path.resolve(__dirname, '..', 'src', '_safelisted.html');
    const cfg = {
      content: [ abs ],
      safelist: ['bg-slate-800','p-2','rounded-xl','hover:border-emerald-500/50','from-emerald-900','backdrop-blur']
    };
    const plugin = tailwindPlugin({ config: cfg });
    const result = await postcss([ plugin, autoprefixer() ]).process(css, { from: undefined });
    fs.writeFileSync('/tmp/tw-inline-out.css', result.css);
    console.log('wrote /tmp/tw-inline-out.css, size=', fs.statSync('/tmp/tw-inline-out.css').size);
  }catch(err){
    console.error('ERROR:', err && err.stack || err);
    process.exit(1);
  }
})();
