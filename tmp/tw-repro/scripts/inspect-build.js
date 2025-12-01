const path = require('path');
const fs = require('fs');
const libPath = path.resolve(__dirname, '..', 'node_modules', 'tailwindcss', 'dist', 'lib.js');
const lib = require(libPath);
const config = require(path.resolve(__dirname, '..', 'tailwind.config.cjs'));

async function inspect() {
  try {
    const compiled = await lib.compile('@tailwind utilities', { config });
    console.log('compile result features:', compiled.features);
    const safelist = (config.safelist || []).map(s => s.toString());
    console.log('safelist candidates:', safelist);

    // build with safelist candidates
    const q = compiled.build(safelist);
    if (!q) {
      console.log('build returned falsy:', q);
      return;
    }
    // q is a Tailwind CSS AST. We'll traverse to collect selector strings.
    function walk(node, acc) {
      if (!node || !node.nodes) return;
      for (const n of node.nodes) {
        if (n.type === 'rule' && n.selector) {
          acc.add(n.selector);
        }
        if (n.children) {
          walk(n.children, acc);
        }
        if (n.nodes) walk(n, acc);
      }
    }
    const selectors = new Set();
    // q appears to be an object with .nodes or .children
    if (q.nodes) walk(q, selectors); else walk({nodes: q}, selectors);

    const selArray = Array.from(selectors).sort();
    console.log('Generated selectors count:', selArray.length);
    const show = selArray.slice(0, 200);
    console.log('First generated selectors:\n', show.join('\n'));

    // Check for specific selectors
    const targets = ['.bg-slate-800', '.border-slate-600', '.rounded-xl', '.p-2', '.hover\\:border-emerald-500\\/50', '.from-emerald-900', '.backdrop-blur', '.text-center'];
    for (const t of targets) {
      const found = selArray.some(s => s.includes(t.replace(/\\\\/g, '\\')));
      console.log(`${t}: ${found ? 'FOUND' : 'MISSING'}`);
    }

    // write AST for manual inspection
    fs.writeFileSync(path.resolve(__dirname, '..', 'out-ast.json'), JSON.stringify(q, null, 2));
    console.log('Wrote out-ast.json');
    
      // Try building with an explicit list of candidate strings (useful when safelist contains objects/regex)
      const explicit = ['bg-slate-800','border-slate-600','rounded-xl','p-2','hover:border-emerald-500/50','from-emerald-900','backdrop-blur','text-center'];
      console.log('Trying explicit candidates:', explicit);
      const q2 = compiled.build(explicit);
      console.log('explicit build result truthy?', !!q2);
      try{
        fs.writeFileSync(path.resolve(__dirname, '..', 'out-ast-explicit.json'), JSON.stringify(q2, null, 2));
        console.log('Wrote out-ast-explicit.json');
      }catch(e){ console.error('write explicit ast failed', e); }
  } catch (e) {
    console.error('inspect error:', e && e.stack ? e.stack : e);
  }
}
inspect();
