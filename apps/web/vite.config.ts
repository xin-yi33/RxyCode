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

function stripXtermElectronProbe() {
  return {
    name: "strip-xterm-electron-probe",
    transform(code: string, id: string) {
      if (!id.includes("@xterm") && !id.includes("xterm.mjs")) return null
      if (!code.includes("electron")) return null
      return code.replaceAll("versions?.electron", "versions?.browser")
    },
  }
}

// W9-F1: /api is proxied to the local API in dev so cookies + CSRF stay
// same-origin. Override with VITE_API_TARGET when the API runs elsewhere.
const apiTarget = process.env.VITE_API_TARGET ?? "http://127.0.0.1:8000"

export default defineConfig({
  plugins: [react(), tailwindcss(), stripXtermElectronProbe()],
  resolve: { alias: { "@desktop/sessionVisualState": sessionVisualState } },
  build: { sourcemap: true },
  server: {
    host: "127.0.0.1",
    fs: { allow: [repoRoot] },
    proxy: {
      "/api": {
        target: apiTarget,
        changeOrigin: true,
      },
    },
  },
})
