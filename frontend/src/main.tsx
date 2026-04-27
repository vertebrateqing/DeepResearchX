/**
 * React 应用的入口文件
 *
 * 这个文件是前端程序的第一个执行文件。
 * 它的作用很简单：创建一个 React 根节点，然后把 App 组件渲染到页面上。
 *
 * 类比：就像是 Python 的 if __name__ == '__main__': 入口
 */

// 从 react-dom/client 导入 createRoot
// React 18+ 使用 createRoot 替代旧的 ReactDOM.render
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

// 导入根组件 App
import App from './App'

// 导入全局样式（Tailwind CSS）
import './index.css'

// ---------------------------------------------------------------------------
// 获取 HTML 中的 root 容器
// ---------------------------------------------------------------------------
// document.getElementById('root') 找到 index.html 中的 <div id="root">
// TypeScript 的 ! 是非空断言，告诉编译器这个元素一定存在
const rootElement = document.getElementById('root')!

// ---------------------------------------------------------------------------
// 创建 React 根节点并渲染
// ---------------------------------------------------------------------------
// createRoot(rootElement) 创建一个 React 根
// .render(...) 把 JSX 元素渲染到这个根节点中
// StrictMode 是 React 的开发模式检查工具，会检测潜在问题
const root = createRoot(rootElement)

root.render(
  <StrictMode>
    <App />
  </StrictMode>,
)
