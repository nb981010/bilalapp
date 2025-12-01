module.exports = {
  content: [
    './index.html',
    './index-with-classes.html',
  ],
  // try safelist as regex/object patterns
  safelist: [
    { pattern: /bg-(slate|emerald)-\d{2,3}(?:\/\d{2})?/ },
    { pattern: /border-(slate|emerald)-\d{2,3}(?:\/\d{2})?/, variants: ['hover'] },
    { pattern: /rounded-(xl|2xl)/ },
    { pattern: /p-(2|3|4)/ },
    { pattern: /from-emerald-900/ },
    { pattern: /backdrop-(blur|brightness|contrast)/ },
    'text-center'
  ],
  theme: {
    extend: {},
  },
  plugins: [],
};
