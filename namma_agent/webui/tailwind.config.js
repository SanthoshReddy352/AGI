/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        // Clean blue/white/black palette (adapted from the installer): white panels
        // on a soft blue-grey canvas, near-black ink, a confident blue accent.
        paper: { DEFAULT: "#f6f8fc", soft: "#eef1f7", panel: "#ffffff", sink: "#e9edf5" },
        ink: { DEFAULT: "#10131a", soft: "#5a606e", faint: "#9aa0ad" },
        line: { DEFAULT: "#e6e9f0", soft: "#eff1f6" },
        brand: { DEFAULT: "#2f6bff", soft: "#e7eeff", deep: "#1f4fd6", wash: "#f1f5ff" },
        // Dark surfaces — a cool slate/navy that pairs with the same blue accent, so
        // dark mode is a faithful counterpart of the light theme (not a separate look).
        night: { DEFAULT: "#0d1017", soft: "#141925", panel: "#1a2030", line: "#28303f", ink: "#e7ecf5", faint: "#98a1b3" },
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
