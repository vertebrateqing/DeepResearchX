"""
API 路由定义

这里定义所有后端暴露给前端的 API 端点。
FastAPI 的路由器（APIRouter）用来把相关的路由分组。

每个路由函数上面的 @router.get("/path") 就是定义一个 API 端点：
- @router.get: 处理 GET 请求
- @router.post: 处理 POST 请求

路径参数：{task_id} 这种大括号里的叫路径参数
查询参数：?query=xxx 这种叫查询参数
"""

from typing import Optional
from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import StreamingResponse

from api.documents import documents_router
from api.models import AnalyzeRequest, TaskCreatedResponse, TaskStatusResponse
from api.streaming import analyze_stream, get_task_status

# 创建路由实例
# api_router 是 FastAPI 路由器的实例，所有 API 端点都注册在它上面
api_router = APIRouter()

# 文档上传 / RAG 管理子路由
api_router.include_router(documents_router)


@api_router.post("/analyze", response_model=TaskCreatedResponse)
async def create_analysis_task(request: AnalyzeRequest):
    """
    创建一个新的分析任务。

    这个端点接收用户的查询，返回一个 task_id。
    前端拿到 task_id 后，去 /analyze/stream 端点接收流式结果。

    参数：
        request: AnalyzeRequest — 包含 query（用户问题）和可选的 model

    返回：
        TaskCreatedResponse — 包含 task_id 和状态信息
    """
    import uuid
    task_id = str(uuid.uuid4())
    return TaskCreatedResponse(
        task_id=task_id,
        status="created",
        message=f"任务已创建，正在分析: {request.query[:50]}...",
    )


@api_router.get("/analyze/stream")
async def stream_analysis(
    query: str = Query(..., description="用户的研究问题"),
    model: Optional[str] = Query(None, description="可选的 LLM 模型"),
    session_id: Optional[str] = Query(None, description="可选，已有会话 ID"),
    skip_clarification: bool = Query(False, description="跳过意图澄清（评测模式）"),
    confirmed_query: Optional[str] = Query(None, description="用户确认后的最终 prompt，直接用于研究"),
    document_ids: Optional[list[str]] = Query(
        None,
        description="可选，限定研究只参考这些已上传文档的 doc_id（多个时重复 query 参数）",
    ),
):
    """
    SSE 流式分析端点。

    这是前后端通信的核心接口。前端用 EventSource 连接这个端点，
    后端会持续推送分析过程中的事件（状态更新、报告内容等）。

    参数：
        query: 用户的查询字符串（必填）
        model: 可选的 LLM 模型名称
        confirmed_query: 用户在意图澄清卡片中编辑确认的最终 prompt
        document_ids: 可选，要在哪些上传文档内做 RAG 研究

    返回：
        StreamingResponse — SSE 格式的事件流
    """
    return StreamingResponse(
        analyze_stream(
            query,
            model,
            session_id,
            skip_clarification,
            confirmed_query,
            document_ids,
        ),
        media_type="text/event-stream",
        headers={
            # 禁用缓存，确保每个事件都能实时到达前端
            "Cache-Control": "no-cache",
            # 保持连接打开，支持长时间流式传输
            "Connection": "keep-alive",
        },
    )


@api_router.get("/analyze/{task_id}", response_model=TaskStatusResponse)
async def get_analysis_status(task_id: str):
    """
    查询分析任务的当前状态。

    当 SSE 连接断开后，前端可以用这个接口查询任务是否完成、
    获取最终结果，或者查看失败原因。

    参数：
        task_id: 创建任务时返回的任务 ID

    返回：
        TaskStatusResponse — 任务的完整状态信息
    """
    task = get_task_status(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")

    return TaskStatusResponse(
        task_id=task["task_id"],
        status=task["status"],
        progress=task.get("progress"),
        result=task.get("result"),
        error=task.get("error"),
        created_at=task["created_at"],
        updated_at=task.get("updated_at"),
    )
