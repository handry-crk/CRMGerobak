/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        brand: '#D7191F',
        deep: '#B32E26',
        charcoal: '#1F1A1A',
        tint: '#F7D4D5',
        line: '#EBD9DA',
        okgreen: '#1E8E3E',
      },
      fontFamily: {
        sans: ['"Plus Jakarta Sans"', 'system-ui', '-apple-system', 'Segoe UI', 'Roboto', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
