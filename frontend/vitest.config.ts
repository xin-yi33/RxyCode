import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    include: ['src/**/*.{test,spec}.{js,ts,tsx}', 'tests/**/*.{test,spec}.{js,ts,tsx}'],
    // OpenTUI dual-entry uses bun:test under frontend/opentui-app/
    exclude: [
      '**/node_modules/**',
      '**/dist/**',
      '**/opentui-app/**',
      'e2e/**',
    ],
  },
});
