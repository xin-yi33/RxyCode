import { fileURLToPath, URL } from "node:url"

import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"
import { defineConfig } from "vite"

const repoRoot = fileURLToPath(new URL("../..", import.meta.url))
const sessionVisualState = fileURLToPath(
  new URL(
    "../../frontend/desktop-app/src/renderer/src/components/sessionVisualState.ts",
    import.meta.url,
  ),
)

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@desktop/sessionVisualState": sessionVisualState } },
  build: { sourcemap: true },
  server: {
    host: "127.0.0.1",
    fs: { allow: [repoRoot] },
  },
})
