import { defineConfig } from "vite"

// Tauri expects a fixed dev port and wants to keep its own log on screen.
export default defineConfig({
  clearScreen: false,
  build: { chunkSizeWarningLimit: 1000 },  // three.js alone is about 570 kB
  server: { port: 1420, strictPort: true, watch: { ignored: ["**/src-tauri/**"] } },
})
