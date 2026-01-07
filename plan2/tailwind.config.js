/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
    "./src/**/*.tsx",
    "./src/**/*.ts",
  ],
  theme: {
    extend: {
      colors: {
        sidebar: '#1e293b',
        sidebarBorder: '#334155',
        sidebarHover: 'rgba(255, 255, 255, 0.05)',
      },
    },
  },
  plugins: [],
}