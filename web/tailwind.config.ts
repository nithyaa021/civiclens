/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        canvas: "var(--canvas)",
        surface: "var(--surface)",
        raised: "var(--raised)",
        ink: "var(--ink)",
        muted: "var(--muted)",
        faint: "var(--faint)",
        line: "var(--line)",
        "line-strong": "var(--line-strong)",
        primary: "var(--primary)",
        "primary-hover": "var(--primary-hover)",
        "primary-soft": "var(--primary-soft)",
        positive: "var(--positive)",
        "positive-soft": "var(--positive-soft)",
        warning: "var(--warning)",
        "warning-soft": "var(--warning-soft)",
        critical: "var(--critical)",
        "critical-soft": "var(--critical-soft)",
        info: "var(--info)",
        "info-soft": "var(--info-soft)",
      },
      fontFamily: {
        sans: [
          "Inter Variable",
          "Inter",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "sans-serif",
        ],
      },
      borderRadius: {
        DEFAULT: "6px",
        md: "7px",
        lg: "8px",
      },
      boxShadow: {
        panel: "0 1px 2px rgb(15 23 26 / 0.04)",
        pop: "0 8px 24px rgb(15 23 26 / 0.10), 0 1px 3px rgb(15 23 26 / 0.08)",
      },
      fontSize: {
        "2xs": ["11px", { lineHeight: "15px" }],
      },
    },
  },
  plugins: [],
};
