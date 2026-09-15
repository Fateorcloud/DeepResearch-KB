import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.DRKB_API_PROXY ?? "http://127.0.0.1:8000",
        changeOrigin: true,
        secure: false,
      },
    },
  },
});
