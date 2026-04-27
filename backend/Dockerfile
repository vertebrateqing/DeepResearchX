# 后端 Dockerfile
# Dockerfile 是一个"食谱"，告诉 Docker 怎么构建一个容器镜像

# 基础镜像：Python 3.12 的精简版（slim = 去掉不必要的包，体积更小）
FROM python:3.12-slim

# 设置工作目录，后续命令都在 /app 下执行
WORKDIR /app

# 先复制依赖文件，单独一层可以缓存（依赖不常变，代码常变）
COPY requirements.txt .

# 安装 Python 依赖
# --no-cache-dir 不缓存 pip 下载的包，减小镜像体积
RUN pip install --no-cache-dir -r requirements.txt

# 复制整个后端代码到容器
COPY . .

# 容器启动时执行的命令
# uvicorn 是 ASGI 服务器，main:app 表示 main.py 中的 app 变量
# --host 0.0.0.0 允许外部访问
# --port 8000 监听 8000 端口
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
