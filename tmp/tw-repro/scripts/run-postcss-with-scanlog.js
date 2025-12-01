const path = require('path');
const fs = require('fs');

// Patch the Scanner.scan method to log scanning internals
try {
  const oxide = require('@tailwindcss/oxide');
  if (oxide && oxide.Scanner && oxide.Scanner.prototype) {
    const orig = oxide.Scanner.prototype.scan;
    oxide.Scanner.prototype.scan = function(...args) {
      try {
        console.error('MONKEY-DEBUG: Scanner.scan called. files.length=', (this.files||[]).length, 'globs.length=', (this.globs||[]).length);
      } catch (e) { console.error('MONKEY-DEBUG: scanner log error', e); }
      const res = orig.apply(this, args);
      try {
        console.error('MONKEY-DEBUG: Scanner.scan result count=', (res||[]).length);
        if (Array.isArray(res)) console.error('MONKEY-DEBUG: Scanner.sample=', res.slice(0,50));
      } catch (e) { console.error('MONKEY-DEBUG: scanner result log error', e); }
      return res;
    }
  } else {
    console.error('MONKEY-DEBUG: oxide.Scanner not found');
  }
} catch (e) {
  console.error('MONKEY-DEBUG: require @tailwindcss/oxide failed', e && e.stack ? e.stack : e);
}

// Patch compileAst to log compiler features and sources
try{
  const nodePkg = require('@tailwindcss/node');
  if(nodePkg && nodePkg.compileAst){
    const origCompileAst = nodePkg.compileAst;
    nodePkg.compileAst = async function(...args){
      const res = await origCompileAst.apply(this,args);
      try{
          console.error('MONKEY-DEBUG: compileAst returned, features=', res && res.features, 'hasBuild=', res && typeof res.build);
        console.error('MONKEY-DEBUG: compileAst.features=', res.features);
        console.error('MONKEY-DEBUG: compileAst.root=', res.root);
        if(res.sources) console.error('MONKEY-DEBUG: compileAst.sources.sample=', res.sources.slice(0,20));
        // Wrap the returned compiler's build function to log candidates and output
        if(res && typeof res.build === 'function'){
          const origBuild = res.build.bind(res);
          res.build = function(candidates){
            try{ console.error('MONKEY-DEBUG: g.build called candidates.length=', (candidates||[]).length); if(Array.isArray(candidates)) console.error('MONKEY-DEBUG: g.build.candidates.sample=', candidates.slice(0,50)); }catch(e){console.error('MONKEY-DEBUG: g.build candidates log error',e)}
            const out = origBuild(candidates);
            try{
              const kind = out===null? 'null' : Array.isArray(out)? 'array' : typeof out;
              console.error('MONKEY-DEBUG: g.build returned kind=', kind);
              if(out && out.nodes) console.error('MONKEY-DEBUG: g.build.nodes.length=', out.nodes.length);
              // if out is an AST converted to string via z() it may be string; show truncated
              if(typeof out === 'string') console.error('MONKEY-DEBUG: g.build.string.len=', out.length, 'preview=', out.slice(0,300));
            }catch(e){console.error('MONKEY-DEBUG: g.build output log error',e)}
            return out;
          }
        }
      }catch(e){console.error('MONKEY-DEBUG: compileAst log error',e)}
      return res;
    }
  }
}catch(e){console.error('MONKEY-DEBUG: require @tailwindcss/node failed', e && e.stack ? e.stack : e)}

// Run PostCSS with the installed plugin
(async () => {
  try {
    const postcss = require('postcss');
    const plugin = require('@tailwindcss/postcss');
    const autoprefixer = require('autoprefixer');
    const inputPath = path.resolve(__dirname, '..', 'src', 'input.css');
    const input = fs.readFileSync(inputPath, 'utf8');
    const result = await postcss([plugin(), autoprefixer()]).process(input, { from: inputPath });
    fs.writeFileSync(path.resolve(__dirname, '..', 'out-with-scanlog.css'), result.css, 'utf8');
    console.error('PostCSS finished, wrote out-with-scanlog.css size=', Buffer.byteLength(result.css));
  } catch (e) {
    console.error('POSTCSS-RUN-ERROR', e && e.stack ? e.stack : e);
  }
})();
