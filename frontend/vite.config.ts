import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Same as nginx.conf: /api/* goes to the backend without the /api prefix.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { "/api": { target: "http://localhost:8000", rewrite: (p) => p.replace(/^\/api/, "") } },
  },
});
