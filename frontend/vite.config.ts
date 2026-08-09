import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The frontend is its own deployable: it is never served by FastAPI. In development the proxy
// below forwards API calls to :8000 so the browser sees one origin and CORS stays out of the way;
// in a deployed build, VITE_API_BASE points at the API and CORS handles it.
export default defineConfig({
  plugins: [react()],
  base: "/",
  build: { outDir: "dist", emptyOutDir: true },
  server: {
    // Port 5300, not Vite's default 5173: Windows reserves 5104-5203 for Hyper-V/WSL on this
    // class of machine (`netsh interface ipv4 show excludedportrange protocol=tcp`), and binding
    // anything in that range fails with EACCES even though nothing is listening.
    host: "127.0.0.1",
    port: 5300,
    strictPort: true,
    proxy: {
      "/workspace": { target: "http://localhost:8000", changeOrigin: true, ws: true },
      "/admin": { target: "http://localhost:8000", changeOrigin: true },
      "/api": { target: "http://localhost:8000", changeOrigin: true },
    },
  },
});
