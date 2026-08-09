/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // WCAG 2.1 AA contrast against white; band colour is always paired with a text label
        // and an icon, never used as the sole carrier of priority (UI-7).
        critical: "#b91c1c",
        high: "#c2410c",
        normal: "#1d4ed8",
        low: "#475569",
      },
    },
  },
  plugins: [],
};
