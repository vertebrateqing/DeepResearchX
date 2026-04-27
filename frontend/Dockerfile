# 前端 Dockerfile

# 基础镜像：Node.js 20 的 Alpine 版（Alpine = 超轻量 Linux 发行版）
FROM node:20-alpine

# 设置工作目录
WORKDIR /app

# 先复制 package 文件（利用 Docker 缓存层）
COPY package.json package-lock.json* ./

# 安装 npm 依赖
RUN npm install

# 复制所有前端代码
COPY . .

# 暴露 5173 端口（Vite 默认开发端口）
EXPOSE 5173

# 启动 Vite 开发服务器
# --host 允许外部访问（默认只监听 localhost）
CMD ["npm", "run", "dev", "--", "--host"]
