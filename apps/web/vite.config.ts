import { fileURLToPath, URL } from "node:url"

import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

const repoRoot = fileURLToPath(new URL("../..", import.meta.url))
const sessionVisualState = fileURLToPath(
  new URL(
    "../../frontend/desktop-app/src/renderer/src/components/sessionVisualState.ts",
    import.meta.url,
  ),
)

function unwrapLegacyCss(css: string, name: string): string {
  const needle = `@${name}`
  let out = ""
  let cursor = 0
  while (cursor < css.length) {
    const at = css.indexOf(needle, cursor)
    if (at < 0) {
      out += css.slice(cursor)
      break
    }
    out += css.slice(cursor, at)
    const brace = css.indexOf("{", at + needle.length)
    const semi = css.indexOf(";", at + needle.length)
    if (brace < 0 || (semi !== -1 && semi < brace)) {
      cursor = semi === -1 ? css.length : semi + 1
      continue
    }
    let depth = 0
    let end = brace
    for (; end < css.length; end++) {
      if (css[end] === "{") depth += 1
      else if (css[end] === "}") {
        depth -= 1
        if (depth === 0) {
          end += 1
          break
        }
      }
    }
    out += css.slice(brace + 1, end - 1)
    cursor = end
  }
  return out
}

function legacySafeCss() {
  return {
    name: "legacy-safe-css",
    generateBundle(_options: unknown, bundle: Record<string, { type: string; fileName?: string; source?: string | Uint8Array }>) {
      for (const item of Object.values(bundle)) {
        if (item.type !== "asset" || !item.fileName?.endsWith(".css") || typeof item.source !== "string") {
          continue
        }
        let css = item.source
        for (const name of ["layer", "property", "nest"]) {
          while (css.includes(`@${name}`)) css = unwrapLegacyCss(css, name)
        }
        item.source = css
      }
    },
  }
}

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
  plugins: [react(), stripXtermElectronProbe(), legacySafeCss()],
  resolve: { alias: { "@desktop/sessionVisualState": sessionVisualState } },
  build: {
    sourcemap: true,
    // Keep emitted syntax usable by older embedded Chromium/WebKit engines;
    // this is a syntax target only and does not imply polyfills or support claims.
    target: ["chrome90", "safari14", "es2020"],
  },
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
