/**
 * Vite 配置文件
 *
 * Vite 是一个前端构建工具，比 Webpack 更快。
 * 它的特点是：开发时按需编译（改哪个文件编译哪个），启动速度极快。
 *
 * 这个配置文件告诉 Vite：
 * 1. 使用 React 插件（处理 JSX 语法）
 * 2. 使用 Tailwind CSS 插件（处理原子类样式）
 */

import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// defineConfig 是 Vite 提供的类型安全的配置函数
// 它会根据参数类型提供代码补全和类型检查
export default defineConfig({
  plugins: [
    react(),        // 支持 React 的 JSX 语法和 Fast Refresh（热更新）
    tailwindcss(),  // 支持 Tailwind CSS v4 的原子类
  ],
  server: {
    // 开发服务器配置
    port: 5173,           // 前端运行在 5173 端口
    strictPort: true,     // 如果 5173 被占用，不自动换端口（避免前后端连接混乱）
  },
})
