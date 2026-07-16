import { defineConfig } from 'vitest/config'
import path from 'path'

// Dedicated vitest config (instead of reusing vite.config.ts) so tests don't
// load the react/tailwind plugins — the suite covers pure lib functions and
// runs in a plain node environment.
export default defineConfig({
  resolve: {
    alias: {
      '@shared': path.resolve(__dirname, '../shared'),
    },
  },
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
  },
})
