import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Per-worktree ports: localdev/start-frontend.ps1 sets these so each worktree's dev server
// and its /graphql + /admin proxy point at that worktree's own backend. Defaults match the
// original single-instance behavior when the vars are unset (e.g. a bare `npm run dev`).
const backendPort = process.env.UC_BACKEND_PORT || '8000'
const frontendPort = process.env.UC_FRONTEND_PORT ? Number(process.env.UC_FRONTEND_PORT) : 5173
const backendUrl = `http://localhost:${backendPort}`

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: frontendPort,
    proxy: {
      '/graphql': backendUrl,
      '/admin': backendUrl,
    },
  },
})
