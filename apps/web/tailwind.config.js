/** @type {import('tailwindcss').Config} */
const variableColor = (name) => `rgba(var(--rxy-${name}-rgb), <alpha-value>)`

export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        background: variableColor("bg"),
        sidebar: variableColor("sidebar"),
        foreground: variableColor("fg"),
        muted: variableColor("muted"),
        border: variableColor("border"),
        card: variableColor("card"),
        bubble: variableColor("bubble"),
        running: variableColor("running"),
        waiting: variableColor("waiting"),
        success: variableColor("success"),
        failure: variableColor("failure"),
        "running-ink": variableColor("running-ink"),
        "waiting-ink": variableColor("waiting-ink"),
        "success-ink": variableColor("success-ink"),
        "failure-ink": variableColor("failure-ink"),
        "muted-ink": variableColor("muted-ink"),
        // 强调色：--rxy-accent(-rgb) 由外观引擎按主题写入；accent-ink 固定
        // 白字（与 bg-failure text-white 的既有按钮约定一致）。
        accent: variableColor("accent"),
        "accent-ink": "#ffffff",
      },
      opacity: {
        15: "0.15",
      },
      // Tailwind v4's shadow-sm differs from v3's default; keep the existing
      // console elevation while emitting legacy rgba() syntax.
      boxShadow: {
        sm: "0 1px 3px 0 rgba(0, 0, 0, 0.1), 0 1px 2px -1px rgba(0, 0, 0, 0.1)",
      },
    },
  },
  plugins: [],
}
