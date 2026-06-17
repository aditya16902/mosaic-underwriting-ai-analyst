/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        page:   "#FAFAF8", // warm off-white page background
        ink:    "#14171C", // near-black primary text
        house:  "#3D5A6C", // muted slate-teal — house/brand color
        clay:   "#B5482F", // HIGH severity / concern accent — used sparingly
        olive:  "#5C7A3D", // OPPORTUNITY / healthy signal accent
        warmgray: "#8B8478", // secondary text, borders, dividers
        panel:  "#F3F1EC", // slightly recessed panel background (cards, chat panel)
        line:   "#E3DFD5", // hairline border color
      },
      fontFamily: {
        display: ["'Source Serif 4'", "Georgia", "serif"],
        sans:    ["'Inter'", "system-ui", "sans-serif"],
        mono:    ["'JetBrains Mono'", "'SF Mono'", "monospace"],
      },
    },
  },
  plugins: [],
};
