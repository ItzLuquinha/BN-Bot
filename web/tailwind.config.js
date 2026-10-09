/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        bn: {
          dark: "#0B0F17",       // Fundo geral do app
          card: "#131B2E",       // Fundo dos cards e sidebar
          cardHover: "#1A253D",  // Hover em cards
          border: "#1E2B45",     // Bordas sutis
          green: "#22C55E",      // O Verde "N" da logo
          greenHover: "#16A34A",
          gold: "#F59E0B",       // O Dourado da estrela/arco
          goldHover: "#D97706",
          blue: "#3B82F6",       // O Azul do arco inferior
          blueHover: "#2563EB",
          muted: "#94A3B8",      // Texto secundário cinza
        }
      },
      boxShadow: {
        'glow-green': '0 0 20px -5px rgba(34, 197, 94, 0.4)',
        'glow-blue': '0 0 20px -5px rgba(59, 130, 246, 0.4)',
      }
    },
  },
  plugins: [],
}