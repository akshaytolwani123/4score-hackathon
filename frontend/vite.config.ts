import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
export default defineConfig({ plugins: [react()], server: { allowedHosts: ["4score.akshaytolwani.xyz"], proxy: { '/api': { target: 'http://api:8000', rewrite: p => p.replace(/^\/api/, '') } } } })
