import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

export default defineConfig({
  plugins: [vue()],
  base: './',
  build: {
    // AstrBot 的插件页约定：views/<页面名>/index.html
    outDir: resolve(__dirname, '../views/jev-gateway'),
    emptyOutDir: true,
    cssCodeSplit: false,
    rollupOptions: {
      output: {
        // 打成单文件，避免 iframe 场景下的动态 import 问题
        inlineDynamicImports: true,
        entryFileNames: 'assets/[name]-[hash].js',
        assetFileNames: 'assets/[name]-[hash][extname]',
      },
    },
  },
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
})
