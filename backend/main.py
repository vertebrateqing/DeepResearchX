"""
Financial DeepResearch - FastAPI 后端入口

这是整个后端服务的入口文件。
FastAPI 是一个现代、高性能的 Python Web 框架，特点是：
- 自动根据代码生成 API 文档
- 基于异步（async/await），处理并发效率高
- 类型注解驱动，减少错误

启动命令（开发模式，带热重载）：
    cd backend && uvicorn main:app --reload --host 0.0.0.0 --port 8000

访问 API 文档：
    http://localhost:8000/docs  (Swagger UI，带交互界面)
"""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# 导入我们自己定义的 API 路由
from api.router import api_router

# 创建 FastAPI 应用实例
app = FastAPI(
    title="Financial DeepResearch API",
    description="A股投资分析系统后端 API，支持流式报告生成",
    version="1.0.0",
)


@app.on_event("startup")
async def configure_logging():
    """Configure root logger level so application INFO logs are visible.

    Python's default root logger level is WARNING, which suppresses INFO.
    Uvicorn configures its own loggers but leaves the root logger at WARNING,
    so logger.info() calls in financial_agent modules are silently dropped.
    We raise the root level to INFO at startup so all modules' logs appear.
    """
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setLevel(logging.INFO)
        formatter = logging.Formatter(
            "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        root.addHandler(handler)


# ---------------------------------------------------------------------------
# CORS (跨域资源共享) 配置
# ---------------------------------------------------------------------------
# 前后端分离时，前端 (http://localhost:5173) 需要调用后端 (http://localhost:8000)
# 浏览器的安全策略默认阻止这种跨域请求，所以后端需要明确允许
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # 允许所有来源（开发时方便，生产需限制）
    allow_credentials=True,        # 允许携带 Cookie
    allow_methods=["*"],          # 允许所有 HTTP 方法
    allow_headers=["*"],          # 允许所有请求头
)

# 注册 API 路由
# prefix="/api" 表示所有路由前面都加上 /api
app.include_router(api_router, prefix="/api")


@app.get("/")
async def root():
    """服务健康检查端点"""
    return {"status": "ok", "service": "Financial DeepResearch API"}
