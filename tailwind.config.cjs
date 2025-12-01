/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './index.html',
    './public/**/*.html',
    './src/**/*.{js,ts,jsx,tsx}',
    './components/**/*.{js,ts,jsx,tsx}',
  ],

  safelist: [
    { pattern: /bg-(.*)/ },
    { pattern: /text-(.*)/ },
    { pattern: /from-(.*)/ },
    { pattern: /to-(.*)/ },
    { pattern: /shadow-(.*)/ },
    { pattern: /ring-(.*)/ },
    { pattern: /rounded-(.*)/ },
    { pattern: /border-(.*)/ },
  ],

  theme: {
    extend: {},
  },

  plugins: [],
}
