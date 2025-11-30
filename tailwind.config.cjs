/** @type {import('tailwindcss').Config} */
console.log('Loading tailwind.config.cjs');
module.exports = {
  content: [
    './index.html',
    './src/**/*.{js,ts,jsx,tsx}',
    './components/**/*.{js,ts,jsx,tsx}',
    './**/*.{js,ts,jsx,tsx,html}'
  ],
  // Safelist classes that may be generated dynamically in templates
  safelist: [
    // Specific utilities used throughout the app
    'bg-slate-800',
    'bg-slate-900',
    'border-slate-600',
    'border-slate-700',
    'text-slate-200',
    'text-slate-300',
    'text-slate-400',
    'text-emerald-50',
    'text-emerald-400',
    'bg-emerald-600',
    'bg-emerald-900',
    'rounded-xl',
    'rounded-2xl',
    'p-2',
    'p-3',
    'p-4',
    'px-4',
    'py-2',
    'shadow-xl',
    'shadow-2xl',
    // Hover/variant rules used in templates (escaped forms are fine here)
    'hover:border-emerald-500/50',
    'hover:bg-slate-700',
    'hover:bg-slate-800/50',
    // Regex fallback to cover other numeric shades and common patterns
    /bg-slate-(?:[0-9]{2,3})(?:\/\d+)?/, /border-slate-(?:[0-9]{2,3})/, /text-slate-(?:[0-9]{2,3})/, /bg-emerald-(?:[0-9]{2,3})(?:\/\d+)?/, /border-emerald-(?:[0-9]{2,3})/, /rounded-(?:xl|2xl|full|lg|md)/
  ],
  theme: {
    extend: {},
  },
  plugins: [],
}
