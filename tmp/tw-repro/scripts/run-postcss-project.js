const path = require('path');
const fs = require('fs');
(async ()=>{
  try{
    const postcss = require('postcss');
    const plugin = require('@tailwindcss/postcss');
    const autoprefixer = require('autoprefixer');
    const inputPath = path.resolve(process.cwd(), 'src', 'index.css');
    const input = fs.readFileSync(inputPath, 'utf8');
    const result = await postcss([plugin(), autoprefixer()]).process(input, { from: inputPath });
    fs.writeFileSync(path.resolve(process.cwd(), 'out-project.css'), result.css, 'utf8');
    console.error('PostCSS finished, wrote out-project.css size=', Buffer.byteLength(result.css));
  }catch(e){
    console.error('POSTCSS-PROJ-ERROR', e && e.stack ? e.stack : e);
    process.exit(1);
  }
})();
