import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@shared': path.resolve(__dirname, '../shared'),
    },
  },
  server: {
    // Allow Tailscale MagicDNS hostnames (e.g. mypc.tailnet.ts.net) through
    // Vite's host check when launched via Run-Tailscale.bat. Localhost and raw
    // IPs (incl. Tailscale's 100.x) are always allowed regardless.
    allowedHosts: ['.ts.net'],
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      '/portraits': 'http://127.0.0.1:8000',
      '/health': 'http://127.0.0.1:8000',
    },
  },
})
