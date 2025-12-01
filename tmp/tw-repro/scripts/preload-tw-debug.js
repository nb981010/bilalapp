// Preload script to instrument Tailwind compiler build()
// Require this with: NODE_OPTIONS="--require /path/to/preload-tw-debug.js"
try {
  const nodePkg = require('@tailwindcss/node');
  if (nodePkg && nodePkg.compileAst) {
    const origCompileAst = nodePkg.compileAst;
    nodePkg.compileAst = async function(...args) {
      const res = await origCompileAst.apply(this, args);
      try {
        console.error('[PRELOAD-TWDEBUG] compileAst returned, features=', res && res.features, 'hasBuild=', !!(res && res.build));
        if (res && typeof res.build === 'function') {
          const origBuild = res.build.bind(res);
          res.build = function(candidates){
            try{
              console.error('[PRELOAD-TWDEBUG] build called. features=', res.features, 'candidates_len=', (candidates||[]).length);
              if (Array.isArray(candidates)) console.error('[PRELOAD-TWDEBUG] candidates_sample=', candidates.slice(0,50));
            }catch(e){ console.error('[PRELOAD-TWDEBUG] candidates log error', e); }
            const out = origBuild(candidates);
            try{
              const kind = out===null? 'null' : Array.isArray(out)? 'array' : typeof out;
              console.error('[PRELOAD-TWDEBUG] build returned kind=', kind);
              if (Array.isArray(out)) console.error('[PRELOAD-TWDEBUG] build_array_len=', out.length);
              if (out && out.nodes) console.error('[PRELOAD-TWDEBUG] build_nodes_len=', out.nodes.length);
              if (typeof out === 'string') console.error('[PRELOAD-TWDEBUG] build_string_len=', out.length, 'preview=', out.slice(0,300));
            }catch(e){ console.error('[PRELOAD-TWDEBUG] build output log error', e); }
            return out;
          }
        }
      } catch(e){ console.error('[PRELOAD-TWDEBUG] compileAst wrap error', e); }
      return res;
    }
  } else {
    console.error('[PRELOAD-TWDEBUG] @tailwindcss/node.compileAst not found');
  }
} catch (e) {
  console.error('[PRELOAD-TWDEBUG] require @tailwindcss/node failed', e && e.stack ? e.stack : e);
}

// Intercept loading of @tailwindcss/postcss to wrap its plugin factory
try{
  const Module = require('module');
  const origLoad = Module._load;
  Module._load = function(request, parent, isMain) {
    const exported = origLoad.apply(this, arguments);
    try{
      if (request === '@tailwindcss/postcss' && exported) {
        try{
          if (typeof exported === 'function'){
            const origFactory = exported;
            const wrappedFactory = function(...args){
              const plugin = origFactory.apply(this,args);
              try{
                console.error('[PRELOAD-TWDEBUG] @tailwindcss/postcss factory invoked');
                // If plugin returns an object with `plugins` array, try to wrap the inner tailwind plugin Once hook
                if (plugin && Array.isArray(plugin.plugins)){
                  plugin.plugins = plugin.plugins.map(p=>{
                    try{
                      if (p && p.postcssPlugin=== 'tailwindcss' && typeof p.Once === 'function'){
                        const origOnce = p.Once;
                        p.Once = function(...onceArgs){
                          try{ console.error('[PRELOAD-TWDEBUG] tailwind-postcss Once called. onceArgs_len=', (onceArgs||[]).length); }catch(e){}
                          return origOnce.apply(this, onceArgs);
                        }
                      }
                    }catch(e){ console.error('[PRELOAD-TWDEBUG] wrap inner plugin error', e); }
                    return p;
                  });
                }
              }catch(e){ console.error('[PRELOAD-TWDEBUG] factory wrapper error', e); }
              return plugin;
            }
            Object.assign(wrappedFactory, origFactory);
            return wrappedFactory;
          }
        }catch(e){ console.error('[PRELOAD-TWDEBUG] wrap exported factory failed', e); }
      }
    }catch(e){ console.error('[PRELOAD-TWDEBUG] Module._load wrapper error', e); }
    return exported;
  }
}catch(e){ console.error('[PRELOAD-TWDEBUG] cannot intercept Module._load', e && e.stack ? e.stack : e); }
// Also wrap the postcss plugin factory to log when the plugin Once() is invoked during PostCSS/Vite runs.
try{
  const postcssPlugin = require('@tailwindcss/postcss');
  if(postcssPlugin){
    const origFactory = postcssPlugin;
    const wrappedFactory = function(...args){
      const pluginObj = origFactory.apply(this,args);
      try{
        // pluginObj may be a function (callable) or an object with plugins array
        const plugins = pluginObj && pluginObj.plugins ? pluginObj.plugins : (Array.isArray(pluginObj)?pluginObj:[]);
        for(const p of plugins){
          if(p && p.postcssPlugin=== 'tailwindcss' && typeof p.Once === 'function'){
            const origOnce = p.Once;
            p.Once = function(...onceArgs){
              try{ console.error('[PRELOAD-TWDEBUG] @tailwindcss/postcss Once invoked'); }catch(e){}
              return origOnce.apply(this, onceArgs);
            }
          }
        }
      }catch(e){ console.error('[PRELOAD-TWDEBUG] wrap postcss plugin error', e); }
      return pluginObj;
    }
    try{
      // replace in require cache so subsequent requires get the wrapped factory
      const resolved = require.resolve('@tailwindcss/postcss');
      const mod = require.cache[resolved];
      if(mod){
        mod.exports = wrappedFactory;
      }
    }catch(e){
      // fallback: set global if direct replacement isn't possible
      try{ global.__PRELOAD_TW_POSTCSS_WRAPPED = wrappedFactory; }catch(_e){}
    }
  }
}catch(e){ console.error('[PRELOAD-TWDEBUG] require @tailwindcss/postcss failed', e && e.stack ? e.stack : e); }
