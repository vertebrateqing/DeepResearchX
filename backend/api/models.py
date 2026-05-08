"""
Pydantic 数据模型定义

Pydantic 是 Python 的数据验证库，用来定义 "数据长什么样"。
好处：
1. 自动验证数据类型（比如要求字段是字符串，传了数字会报错）
2. 自动生成 JSON Schema，API 文档里能看到每个字段的说明
3. 类型安全，配合 IDE 有代码补全
"""

from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import datetime


class AnalyzeRequest(BaseModel):
    """
    发起分析请求的参数

    Field(...) 里的参数：
    - description: API 文档中显示的字段说明
    - examples: 示例值
    """
    query: str = Field(
        ...,
        description="用户的投资分析问题，例如 '腾讯最近值得买入吗'",
        examples=["腾讯最近值得买入吗", "贵州茅台2024年报分析"],
    )
    model: Optional[str] = Field(
        default=None,
        description="可选，指定使用的 LLM 模型，不传则使用默认配置",
        examples=["qwen-plus", "deepseek-chat"],
    )
    session_id: Optional[str] = Field(
        default=None,
        description="可选，指定会话 ID 以恢复已有会话上下文（支持多轮对话）",
        examples=["sess_20250425_143022_a1b2c3"],
    )
    document_ids: Optional[list[str]] = Field(
        default=None,
        description="可选，限定研究只参考这些已上传的文档 doc_id",
    )


class TaskCreatedResponse(BaseModel):
    """创建分析任务后的响应"""
    task_id: str = Field(description="任务唯一 ID，用于后续查询和流式接收结果")
    status: Literal["created", "queued"] = Field(description="任务当前状态")
    message: str = Field(description="给用户看的状态说明")


class TaskStatusResponse(BaseModel):
    """查询任务状态的响应"""
    task_id: str
    status: Literal["pending", "running", "completed", "failed"] = Field(
        description="pending=排队中, running=分析中, completed=已完成, failed=失败"
    )
    progress: Optional[int] = Field(
        default=None,
        description="进度百分比 0-100",
    )
    result: Optional[dict] = Field(
        default=None,
        description="分析完成后的完整结果（仅 status=completed 时有值）",
    )
    error: Optional[str] = Field(
        default=None,
        description="失败原因（仅 status=failed 时有值）",
    )
    created_at: datetime = Field(description="任务创建时间")
    updated_at: Optional[datetime] = Field(description="最后更新时间")


class StreamEvent(BaseModel):
    """
    SSE (Server-Sent Events) 流式事件

    后端会持续推送这类事件给前端，就像 ChatGPT 那样逐字显示。
    event 字段表示事件类型，前端根据类型决定怎么展示。
    """
    event: Literal[
        "connected",
        "status",
        "progress",
        "thinking",
        "tool_call",
        "tool_result",
        "chapter",
        "content",
        "chart",
        "sources",
        "error",
        "complete",
    ] = Field(description="事件类型")
    data: dict = Field(description="事件携带的数据")
    timestamp: datetime = Field(
        default_factory=datetime.now,
        description="事件发生时间",
    )


# ---------------------------------------------------------------------------
# Document upload / RAG models (used by /api/documents/*)
# ---------------------------------------------------------------------------


class DocumentInfo(BaseModel):
    """已入库文档的元数据。"""

    doc_id: str = Field(description="文档唯一 ID（服务端生成）")
    filename: str = Field(description="原始文件名")
    extension: str = Field(description="文件扩展名，例如 .pdf / .docx")
    size_bytes: int = Field(default=0, description="原始文件大小（字节）")
    char_count: int = Field(default=0, description="抽取后的文本字符数")
    chunks: int = Field(default=0, description="切分后的向量块数量")
    uploaded_at: str = Field(default="", description="入库时间（ISO 字符串）")


class DocumentUploadResponse(BaseModel):
    """上传接口的响应。"""

    session_id: str
    collection: str = Field(description="后端为本会话生成的向量集合名称")
    uploaded: list[DocumentInfo] = Field(description="入库成功的文档列表")
    failed: list[dict] = Field(
        default_factory=list,
        description="入库失败的文件，包含 filename 和 error 字段",
    )


class DocumentListResponse(BaseModel):
    """列出会话文档的响应。"""

    session_id: str
    collection: str
    documents: list[DocumentInfo]


class DocumentDeleteResponse(BaseModel):
    """删除单个文档的响应。"""

    session_id: str
    doc_id: str
    chunks_removed: int
    file_removed: bool
