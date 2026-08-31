import { resolve } from 'path'
import { defineConfig } from 'electron-vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  main: {
    build: {
      // Bundle @rxycode/protocol-client (ships TypeScript) into the main
      // bundle: the packaged app cannot type-strip TS under node_modules
      // inside app.asar (Phase4-D6, verified via packaged smoke).
      externalizeDeps: false,
      rollupOptions: {
        external: ['electron']
      }
    }
  },
  preload: {
    build: {
      // Sandboxed preloads can only require('electron') and Node's
      // built-in allowlist, so bundle @electron-toolkit/preload instead
      // of leaving it as an external require.
      externalizeDeps: false,
      rollupOptions: {
        external: ['electron']
      }
    }
  },
  renderer: {
    publicDir: resolve('src/renderer/public'),
    // Inline (empty) PostCSS config so Vite does not walk up to
    // frontend/package.json, which carries a UTF-8 BOM and breaks
    // postcss-load-config (baseline issue; fixed in-scope only).
    css: {
      postcss: {}
    },
    resolve: {
      alias: {
        '@renderer': resolve('src/renderer/src')
      }
    },
    plugins: [react()]
  }
})
