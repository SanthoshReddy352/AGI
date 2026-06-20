/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        // claude.ai-style warm palette
        paper: { DEFAULT: "#faf9f5", soft: "#f3f1ea", panel: "#ffffff", sink: "#efece3" },
        ink: { DEFAULT: "#2d2a26", soft: "#6b6760", faint: "#9c978d" },
        line: { DEFAULT: "#e8e4d9", soft: "#f0ede4" },
        brand: { DEFAULT: "#cc785c", soft: "#e0a890", deep: "#b8623f", wash: "#f6ece6" },
        // dark surfaces
        night: { DEFAULT: "#262624", soft: "#30302e", panel: "#2f2f2d", line: "#3d3d3a", ink: "#ece9e2", faint: "#a8a39a" },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "Segoe UI", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular", "monospace"],
        serif: ["Georgia", "ui-serif", "serif"],
      },
      boxShadow: {
        soft: "0 1px 3px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04)",
        pop: "0 8px 30px -12px rgba(0,0,0,0.18)",
      },
      keyframes: {
        rise: { from: { opacity: "0", transform: "translateY(6px)" }, to: { opacity: "1", transform: "translateY(0)" } },
        blink: { "0%,100%": { opacity: "1" }, "50%": { opacity: "0.25" } },
      },
      animation: {
        rise: "rise 0.22s ease-out",
        blink: "blink 1s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};
