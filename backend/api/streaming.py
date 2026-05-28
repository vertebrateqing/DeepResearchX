"""
流式分析服务

把原有的分析流程（Orchestrator）包装成支持 SSE 流式推送的服务。
核心思路：
1. 接收用户的查询
2. 启动异步任务执行分析
3. 通过 async generator (async for) 逐段产出事件
4. 前端通过 EventSource 接收这些事件并实时展示

为什么用 SSE 而不是 WebSocket？
- SSE 是单向的（后端→前端），实现更简单
- 自动重连、基于 HTTP，兼容性好
- 我们的场景只需要后端推数据给前端，不需要前端实时发数据给后端
"""

import asyncio
import uuid
import logging
from datetime import datetime
from typing import AsyncGenerator, Optional

from deep_research.core.orchestrator import OrchestratorAgent
from api.models import StreamEvent

logger = logging.getLogger(__name__)

# 内存中的任务存储（生产环境应改为 Redis / 数据库）
_task_store: dict[str, dict] = {}


def _validate_session_id(session_id: Optional[str]) -> Optional[str]:
    """Validate session_id to prevent path traversal attacks.

    Returns the sanitized session_id or None if invalid.
    """
    if not session_id:
        return None
    sid = session_id.strip()
    if any(c in sid for c in "/\\.."):
        return None
    return sid


async def analyze_stream(
    query: str,
    model: Optional[str] = None,
    session_id: Optional[str] = None,
    skip_clarification: bool = False,
    confirmed_query: Optional[str] = None,
    document_ids: Optional[list[str]] = None,
    documents_only: bool = False,
) -> AsyncGenerator[str, None]:
    """
    执行分析并以 SSE 格式流式返回结果。

    SSE 格式要求：每行以 'data: ' 开头，以两个换行符结束一条消息。
    例如：
        data: {"event": "status", "data": {"message": "开始分析"}}\n\n

    参数：
        query: 用户的查询，如 "腾讯最近值得买入吗"
        model: 可选，指定 LLM 模型
        document_ids: 可选，限定研究只引用这些上传文档

    返回：
        AsyncGenerator，每次 yield 一条 SSE 格式的字符串
    """
    # Validate session_id to prevent path traversal
    validated_session = _validate_session_id(session_id)
    if session_id and validated_session is None:
        yield _sse_format("error", {"message": "Invalid session_id"})
        return
    session_id = validated_session

    task_id = str(uuid.uuid4())

    # 记录任务到内存存储
    _task_store[task_id] = {
        "task_id": task_id,
        "query": query,
        "status": "running",
        "progress": 0,
        "result": None,
        "error": None,
        "created_at": datetime.now(),
        "updated_at": datetime.now(),
    }

    # 发送 "已连接" 事件，前端收到后可以显示 "分析已开始"
    yield _sse_format("connected", {"task_id": task_id, "message": "分析任务已创建"})

    try:
        # 创建进度事件队列，用于 orchestrator 回调和 SSE 生产之间的通信
        progress_queue: asyncio.Queue[dict] = asyncio.Queue()

        def on_progress(event_type: str, payload: dict) -> None:
            """Orchestrator 回调，把进度事件放入队列。"""
            try:
                progress_queue.put_nowait({"event": event_type, "data": payload})
            except Exception:
                pass

        # 创建原有 Orchestrator 实例，传入进度回调
        # 如果传了 session_id，OrchestratorAgent 会自动加载该会话的上下文
        # 这样就能支持多轮对话（澄清 → 回复 → 继续分析）
        orchestrator = OrchestratorAgent(
            session_id=session_id,
            progress_callback=on_progress,
            skip_clarification=skip_clarification,
            document_ids=document_ids or None,
            documents_only=documents_only,
        )

        # 如果前端传入了用户确认的最终 prompt，直接用它研究，跳过澄清流程
        effective_query = confirmed_query if confirmed_query else query

        # 启动分析任务（在后台运行）
        run_task = asyncio.create_task(orchestrator.run(effective_query, confirmed_query=bool(confirmed_query)))

        # 并发消费进度事件队列，直到分析任务完成
        import time as _time
        _last_ping = _time.monotonic()
        while not run_task.done():
            try:
                # 等待队列事件，超时后检查任务是否完成
                event = await asyncio.wait_for(progress_queue.get(), timeout=0.5)
                yield _sse_format(event["event"], event["data"])
                _last_ping = _time.monotonic()
            except asyncio.TimeoutError:
                # Send SSE comment as keepalive every 30s to prevent connection timeout
                if _time.monotonic() - _last_ping > 30:
                    yield ": ping\n\n"
                    _last_ping = _time.monotonic()
                continue

        # 分析任务完成后，清空队列中剩余的事件
        while not progress_queue.empty():
            try:
                event = progress_queue.get_nowait()
                yield _sse_format(event["event"], event["data"])
            except asyncio.QueueEmpty:
                break

        # 获取分析结果（await 会重新抛出任务中的异常）
        result = await run_task

        # 更新进度
        _task_store[task_id]["progress"] = 100
        _task_store[task_id]["result"] = result
        _task_store[task_id]["status"] = "completed"
        _task_store[task_id]["updated_at"] = datetime.now()

        # 处理返回结果
        # result 是 AgentMessage，报告内容在 result.content 中
        if result.is_error():
            yield _sse_format("error", {"message": str(result.content), "task_id": task_id})
        else:
            content = result.content if isinstance(result.content, dict) else {}
            # 处理需要澄清的情况
            if content.get("requires_clarification"):
                yield _sse_format("clarification", {
                    "question": content.get("prompt", ""),
                    "enriched_query": content.get("enriched_query", ""),
                    "plan_brief": content.get("plan_brief", ""),
                })
                yield _sse_format("complete", {"task_id": task_id, "message": "等待用户确认"})
            else:
                # 正常报告
                yield _sse_format("content", {"text": content.get("report", "")})
                yield _sse_format("complete", {"task_id": task_id, "message": "分析完成"})

    except Exception as e:
        logger.exception(f"Task {task_id} failed")
        _task_store[task_id]["status"] = "failed"
        _task_store[task_id]["error"] = str(e)
        _task_store[task_id]["updated_at"] = datetime.now()
        yield _sse_format("error", {"message": str(e), "task_id": task_id})


def get_task_status(task_id: str) -> dict | None:
    """查询任务当前状态"""
    return _task_store.get(task_id)


def _sse_format(event: str, data: dict) -> str:
    """
    将事件和数据格式化为 SSE 格式字符串。

    SSE 协议格式（每行以 \n 结尾，消息之间用 \n\n 分隔）：
        event: <事件类型>\n
        data: <JSON 数据>\n\n

    参数：
        event: 事件类型，如 "status", "content", "error"
        data:  要发送的数据字典，会被转成 JSON 字符串

    返回：
        SSE 格式的字符串
    """
    import json
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
