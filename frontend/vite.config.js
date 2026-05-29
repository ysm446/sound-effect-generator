import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Renderer build. base "./" so the built index.html works when loaded from
// the local filesystem by Electron in production.
export default defineConfig({
  plugins: [react()],
  base: "./",
  server: {
    port: 5173,
    strictPort: true,
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
