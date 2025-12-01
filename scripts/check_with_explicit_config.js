const fs = require('fs');
const path = require('path');
const postcss = require('postcss');
const tailwindPlugin = require('@tailwindcss/postcss');
const autoprefixer = require('autoprefixer');
(async ()=>{
  try{
    const css = '@tailwind utilities;';
    const plugin = tailwindPlugin({ config: path.resolve(__dirname, '..', 'tailwind.test.config.cjs') });
    const result = await postcss([ plugin, autoprefixer() ]).process(css, { from: undefined });
    console.log(result.css);
  }catch(err){
    console.error('ERROR:', err && err.stack || err);
    process.exit(1);
  }
})();
