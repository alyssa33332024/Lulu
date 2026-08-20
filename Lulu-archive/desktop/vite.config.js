import { defineConfig } from 'vite';

export default defineConfig({
  server: {
    port: 5173,
    host: '127.0.0.1',
    strictPort: true,
    open: false,
  },
  publicDir: 'public',
});
