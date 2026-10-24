/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: { DEFAULT: "#0B0B0C", 2: "#3A3A3D", 3: "#6E6E73", 4: "#A1A1A6" },
        line: { DEFAULT: "#E7E7E4", 2: "#F1F1EE" },
        paper: { DEFAULT: "#FFFFFF", 2: "#FAFAF8", 3: "#F4F4F1" },
        accent: { DEFAULT: "#FF5A1F", soft: "#FFF1EB", deep: "#D9430E" },
        slate: { DEFAULT: "#8C93A3" },
      },
      fontFamily: {
        sans: ['"Inter Variable"', "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ['"JetBrains Mono Variable"', "ui-monospace", "SFMono-Regular", "monospace"],
      },
      boxShadow: { card: "0 1px 0 rgba(11,11,12,0.04), 0 1px 2px rgba(11,11,12,0.04)" },
      keyframes: {
        rise: { "0%": { opacity: 0, transform: "translateY(8px)" }, "100%": { opacity: 1, transform: "none" } },
        pulsedot: { "0%,100%": { opacity: 1 }, "50%": { opacity: 0.25 } },
      },
      animation: { rise: "rise .45s cubic-bezier(.2,.7,.2,1) both", pulsedot: "pulsedot 1.2s ease-in-out infinite" },
    },
  },
  plugins: [],
};
