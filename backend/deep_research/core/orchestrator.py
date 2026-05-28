"""Orchestrator agent — Planner-Worker-Synthesizer (PWS) architecture.

V4 features:
- OutlinePlanner: LLM-generated report outline with chapter breakdown
- ChapterWorker: autonomous per-chapter research & writing
- ReviserAgent: quality review loop per chapter
- IntegrationAgent: merge chapters into coherent draft
- EditorAgent: final polish for grammar, facts, completeness
- Report export to MD/PDF
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

import asyncio

from deep_research.config.settings import get_settings
from deep_research.core.agent import LLMClient, SimpleAgent
from deep_research.observability import get_langfuse
from deep_research.core.base import AgentContext, BaseAgent, BaseSkill, BaseTool
from deep_research.core.chapter_worker import ChapterWorker, _extract_sources_from_text
from deep_research.core.editor import EditorAgent
from deep_research.core.finding import Finding
from deep_research.core.intent_clarifier import (
    ClarificationResult,
    IntentClarifier,
    ResearchPlanBrief,
)
from deep_research.core.integration import IntegrationAgent
from deep_research.core.message import AgentMessage
from deep_research.core.outline_planner import ChapterOutline, OutlinePlanner, ReportOutline
from deep_research.core.report_generator import ReportGenerator
from deep_research.core.reviser import ReviserAgent
from deep_research.memory.manager import MemoryManager

logger = logging.getLogger(__name__)


class OrchestratorAgent(BaseAgent):
    """Main orchestrator using V4 multi-phase report generation.

    Pipeline:
    1. Intent clarification (HITL)
    2. OutlinePlanner generates report outline
    3. All chapters execute in parallel with pre-search context
    4. ReviserAgent reviews each chapter (revision loop)
    5. IntegrationAgent merges chapters into draft
    6. EditorAgent polishes the draft
    7. Report exported to MD/PDF
    """

    def __init__(
        self,
        name: str = "orchestrator",
        system_prompt: str = "",
        tools: Optional[list[BaseTool]] = None,
        skills: Optional[list[BaseSkill]] = None,
        model: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: str = "anonymous",
        progress_callback: Optional[Callable[..., None]] = None,
        skip_clarification: bool = False,
        document_ids: Optional[list[str]] = None,
        document_collection: Optional[str] = None,
        documents_only: bool = False,
    ):
        cfg = get_settings().agents.orchestrator
        super().__init__(
            name=name,
            system_prompt=system_prompt or cfg.system_prompt,
            tools=tools,
            skills=skills,
        )
        self.model = model or cfg.model
        self.llm_agent = SimpleAgent(
            name=f"{name}_llm",
            system_prompt=self.system_prompt,
            model=self.model,
        )
        self.progress_callback = progress_callback
        self.skip_clarification = skip_clarification
        _lf_cfg = get_settings().langfuse
        self._record_dataset = _lf_cfg.record_dataset
        self._dataset_max_items = max(1, _lf_cfg.dataset_max_items)

        # V4 components
        self.intent_clarifier = IntentClarifier()
        self.outline_planner = OutlinePlanner()
        self.reviser = ReviserAgent()
        self.integration = IntegrationAgent()
        self.editor = EditorAgent()
        self.memory = MemoryManager(
            session_id=session_id or self._generate_session_id(),
            user_id=user_id,
        )
        self.memory.init_session()

        # Optional uploaded-document context for RAG-based deepresearch.
        # If document_collection is not given but document_ids are, derive
        # the collection from session_id (matches /api/documents/upload).
        from deep_research.rag.pipeline import collection_for_session

        self.document_ids: Optional[list[str]] = (
            list(document_ids) if document_ids else None
        )
        if document_collection:
            self.document_collection: Optional[str] = document_collection
        elif self.document_ids:
            self.document_collection = collection_for_session(self.memory.session_id)
        else:
            self.document_collection = None

        self.documents_only = documents_only

        # Clarification state
        self._clarification_result: Optional[ClarificationResult] = None
        self._total_clarification_rounds: int = 0
        self._confirmed_plan_brief: Optional[ResearchPlanBrief] = None   # User-confirmed research plan

        # 恢复已有会话的澄清状态（支持多轮对话）
        cs = self.memory.session.clarification_state
        if cs and cs.get("status") == "clarifying":
            self._total_clarification_rounds = cs.get("round", 0)
            self._clarification_result = ClarificationResult(
                complete=False,
                original_query=cs.get("original_query", ""),
                enriched_query=cs.get("enriched_query", ""),
                clarification_question=cs.get("clarification_question", ""),
                rounds_completed=cs.get("round", 0),
            )
            logger.info(
                f"[Orchestrator] 恢复澄清状态: rounds={self._total_clarification_rounds}, "
                f"question={self._clarification_result.clarification_question[:50]}"
            )

    def _emit(self, event_type: str, payload: dict) -> None:
        """Emit a progress event via the callback if configured."""
        if self.progress_callback is not None:
            try:
                self.progress_callback(event_type, payload)
            except Exception:
                pass

    def _generate_session_id(self) -> str:
        return f"sess_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"

    @property
    def session_dir(self) -> Path:
        """Directory for this session's working files."""
        sid = self.memory.session_id
        if any(c in sid for c in "/\\.."):
            raise ValueError(f"Invalid session_id: {sid}")
        base = Path("./deep_research/data/sessions").resolve()
        path = base / sid
        # Defensive: ensure resolved path stays within base directory
        if not str(path.resolve()).startswith(str(base)):
            raise ValueError(f"Session directory escape detected: {path}")
        return path

    async def run(
        self,
        user_input: str,
        context: Optional[AgentContext] = None,
        confirmed_query: bool = False,
    ) -> AgentMessage:
        """Run the full deepresearch pipeline.

        Args:
            user_input: User's query or confirmed enriched prompt.
            confirmed_query: When True, user_input is already the final enriched
                prompt confirmed by the user — skip clarification entirely.
        """
        logger.info(f"Orchestrator received request: {user_input[:100]}...")

        # Create Langfuse trace for this request
        lf = get_langfuse()
        if lf:
            self._lf_trace = lf.trace(
                name="deepresearch",
                session_id=self.memory.session_id,
                input={"query": user_input},
                metadata={"model": get_settings().llm.model},
            )
            self._trace_id: Optional[str] = self._lf_trace.id
        else:
            self._lf_trace = None
            self._trace_id = None

        # Propagate trace_id to all component LLM clients
        for component in (self.llm_agent, self.intent_clarifier, self.outline_planner,
                          self.reviser, self.integration, self.editor):
            if hasattr(component, "llm"):
                component.llm._trace_id = self._trace_id

        # Record user message
        self.memory.add_user_message(user_input)
        detected_prefs = self.memory.detect_preferences_from_query(user_input)
        if detected_prefs:
            self.memory.update_preferences(**detected_prefs)

        # If user confirmed enriched query from the clarification card, use directly
        if confirmed_query:
            self._clarification_result = None
            return await self._execute_research(user_input, user_input, context)

        # Step 1: Handle ongoing clarification
        if self._clarification_result and not self._clarification_result.complete:
            return await self._handle_clarification_response(user_input)

        if self._clarification_result is None:
            self._total_clarification_rounds = 0

        # Step 2: Intent clarification → structured research plan brief
        self._emit("status", {"message": "正在理解您的问题...", "stage": "intent", "progress": 5})
        if self.skip_clarification or self._total_clarification_rounds >= IntentClarifier.MAX_ROUNDS:
            clarification = ClarificationResult(
                complete=True,
                original_query=user_input,
                plan_brief=ResearchPlanBrief(research_topic=user_input),
            )
        else:
            clarification = await self.intent_clarifier.analyze(user_input)

        if not clarification.complete:
            self._clarification_result = clarification
            self.memory.session.clarification_state = {
                "status": "clarifying",
                "round": clarification.rounds_completed,
                "original_query": clarification.original_query,
                "clarification_question": clarification.clarification_question,
            }
            await self.memory.save(sync_long_term=False)

            question_text = clarification.clarification_question
            self.memory.add_assistant_message(question_text)

            return AgentMessage.create_result(
                sender=self.name,
                receiver="user",
                result={
                    "requires_clarification": True,
                    "prompt": question_text,
                    "plan_brief": clarification.plan_brief.to_prompt_block() if clarification.plan_brief else "",
                },
            )

        # Save confirmed plan brief for downstream injection
        self._confirmed_plan_brief = clarification.plan_brief

        # Step 3: Execute deepresearch
        # Build enriched_query from plan_brief for backward compatibility
        enriched_query = (
            clarification.plan_brief.to_prompt_block()
            if clarification.plan_brief
            else user_input
        )
        return await self._execute_research(
            enriched_query, user_input, context, plan_brief=clarification.plan_brief
        )

    async def _execute_research(
        self,
        merged_query: str,
        original_query: str,
        context: Optional[AgentContext] = None,
        plan_brief: Optional[ResearchPlanBrief] = None,
    ) -> AgentMessage:
        """Execute V4 research pipeline."""
        from datetime import datetime
        now = datetime.now()
        date_context = f"【当前真实日期：{now.strftime('%Y年%m月%d日')}】"
        enriched_query = f"{merged_query}\n\n{date_context}"

        # If user uploaded documents, surface that to the planner so it
        # treats them as authoritative sources alongside the web.
        document_hint = self._build_document_hint()
        if document_hint:
            enriched_query = f"{enriched_query}\n\n{document_hint}"

        logger.info(f"[Orchestrator] Starting V4 pipeline for: {enriched_query[:100]}...")
        session_dir = self.session_dir
        session_dir.mkdir(parents=True, exist_ok=True)

        lf = get_langfuse()
        trace_id = getattr(self, "_trace_id", None)

        # Record main task
        main_task = self.memory.start_task(
            task_type="deepresearch",
            agent=self.name,
            inputs={"query": original_query, "enriched_query": enriched_query},
        )

        # --- Phase 1: Generate outline ---
        self._emit("status", {"message": "正在规划报告结构...", "stage": "outline", "progress": 10})
        logger.info("[Orchestrator] Phase 1: Generating report outline")
        t0 = time.perf_counter()
        span_outline = lf.span(trace_id=trace_id, name="outline_planning", input={"query": enriched_query[:200]}) if lf and trace_id else None
        outline = await self.outline_planner.generate_outline(
            user_query=enriched_query,
            save_dir=session_dir,
        )
        t1 = time.perf_counter()
        if span_outline:
            span_outline.end(output={"title": outline.title, "chapters": [c.chapter_id for c in outline.chapters]}, metadata={"latency_s": round(t1 - t0, 3)})
        logger.info(
            f"[Orchestrator] Phase 1 DONE: outline_gen={t1-t0:.2f}s, "
            f"title='{outline.title}', chapters={len(outline.chapters)}"
        )
        for ch in outline.chapters:
            logger.debug(
                f"[Orchestrator] Outline chapter: {ch.chapter_id} "
                f"tools={ch.suggested_tools}"
            )

        # --- Phase 2: Execute chapters with review ---
        self._emit("status", {"message": "正在进行深度研究...", "stage": "chapters", "progress": 30})
        logger.info("[Orchestrator] Phase 2: Executing chapters with review")
        t0 = time.perf_counter()
        span_chapters = lf.span(trace_id=trace_id, name="chapter_execution") if lf and trace_id else None
        chapter_files, chapter_findings = await self._execute_chapters(
            outline=outline,
            session_dir=session_dir,
            trace_id=trace_id,
        )
        t1 = time.perf_counter()
        passed_count = sum(
            1 for f in chapter_findings if f.details.get("review_passed", True)
        )
        if span_chapters:
            span_chapters.end(output={"chapters": len(chapter_files), "passed": passed_count}, metadata={"latency_s": round(t1 - t0, 3)})
        logger.info(
            f"[Orchestrator] Phase 2 DONE: chapter_exec={t1-t0:.2f}s, "
            f"chapters={len(chapter_files)}, passed={passed_count}"
        )

        # --- Phase 3: Integrate chapters ---
        self._emit("status", {"message": "正在整合各章节...", "stage": "integration", "progress": 60})
        logger.info("[Orchestrator] Phase 3: Integrating chapters")
        t0 = time.perf_counter()
        span_integration = lf.span(trace_id=trace_id, name="integration") if lf and trace_id else None
        self.integration.llm._trace_id = trace_id
        draft_path = await self.integration.integrate(
            title=outline.title,
            summary_points=outline.executive_summary_points,
            chapter_files=chapter_files,
            session_dir=session_dir,
            original_query=original_query,
            plan_brief=plan_brief,
        )
        t1 = time.perf_counter()
        if span_integration:
            span_integration.end(metadata={"latency_s": round(t1 - t0, 3)})
        logger.info(f"[Orchestrator] Phase 3 DONE: integration={t1-t0:.2f}s, draft={draft_path}")

        # --- Phase 4: Editor review & polish ---
        self._emit("status", {"message": "正在审校和润色报告...", "stage": "editing", "progress": 75})
        logger.info("[Orchestrator] Phase 4: Editorial review")
        t0 = time.perf_counter()
        span_editing = lf.span(trace_id=trace_id, name="editorial_review") if lf and trace_id else None
        self.editor.llm._trace_id = trace_id
        final_draft = await self.editor.edit_loop(draft_path, session_dir)
        t1 = time.perf_counter()
        if span_editing:
            span_editing.end(metadata={"latency_s": round(t1 - t0, 3)})
        logger.info(f"[Orchestrator] Phase 4 DONE: editing={t1-t0:.2f}s, final={final_draft}")

        # --- Phase 5: Generate and save report ---
        self._emit("status", {"message": "正在生成最终报告...", "stage": "export", "progress": 90})
        logger.info("[Orchestrator] Phase 5: Generating final report")
        t0 = time.perf_counter()
        final_text = final_draft.read_text(encoding="utf-8")

        # Build sections from chapter files for report metadata
        sections = self._build_sections_from_chapters(chapter_files)

        output_dir = Path(get_settings().output.output_dir)
        generator = ReportGenerator()
        markdown = generator.generate_markdown(
            user_query=original_query,
            final_report=final_text,
            sections=sections,
            session_id=self.memory.session_id,
            is_v4=True,
        )
        md_path, pdf_path = generator.save(
            output_dir=output_dir,
            session_id=self.memory.session_id,
            markdown=markdown,
        )
        t1 = time.perf_counter()
        logger.info(
            f"[Orchestrator] Phase 5 DONE: export={t1-t0:.2f}s, "
            f"md={md_path}, pdf={pdf_path}"
        )

        # Record completion
        self.memory.update_task(
            task_id=main_task.task_id,
            status="completed",
            result={"summary": final_text[:500]},
        )
        self.memory.add_finding(
            source="orchestrator",
            content=final_text[:1000],
            confidence=0.7,
            expires_hours=24,
        )
        self.memory.add_assistant_message(final_text[:500])
        await self.memory.save()

        # Finalize Langfuse trace and optionally record to dataset
        if lf and trace_id:
            try:
                if self._lf_trace:
                    self._lf_trace.update(output={"report_length": len(final_text), "status": "success"})

                if self._record_dataset:
                    cfg = get_settings().langfuse
                    try:
                        lf.create_dataset(name=cfg.dataset_name)
                    except Exception:
                        pass
                    items_written = 0
                    if items_written < self._dataset_max_items:
                        lf.create_dataset_item(
                            dataset_name=cfg.dataset_name,
                            input={"query": original_query, "enriched_query": merged_query},
                            expected_output=final_text,
                            source_trace_id=trace_id,
                            metadata={"session_id": self.memory.session_id},
                        )
                        items_written += 1
                        logger.info(f"[Orchestrator] Langfuse dataset item recorded ({items_written}/{self._dataset_max_items})")

            except Exception as _lf_err:
                logger.warning(f"[Orchestrator] Langfuse finalize failed: {_lf_err}")

        metadata: dict[str, Any] = {}
        if md_path:
            metadata["report_md_path"] = str(md_path)
        if pdf_path:
            metadata["report_pdf_path"] = str(pdf_path)
        metadata["session_dir"] = str(session_dir)
        metadata["chapters"] = len(chapter_files)

        return AgentMessage.create_result(
            sender=self.name,
            receiver="user",
            result={
                "report": final_text,
                "sections": sections,
                "chapters_count": len(chapter_files),
                "outline_title": outline.title,
            },
            task_id=context.task_id if context else None,
            metadata=metadata,
        )

    async def _execute_chapters(
        self,
        outline: ReportOutline,
        session_dir: Path,
        trace_id: Optional[str] = None,
    ) -> tuple[list[Path], list[Finding]]:
        """Execute chapters respecting dependency order (topological).

        Pipeline:
        1. Topological execution: chapters with no pending deps run in parallel batches
        2. Revision loop per chapter after writing
        """
        # --- Step 1: Topological execution ---
        chapter_map = {ch.chapter_id: ch for ch in outline.chapters}
        completed: set[str] = set()
        completed_contents: dict[str, str] = {}   # chapter_id → full text for dependency injection
        chapter_findings: list[Finding] = []
        chapter_files: list[Path] = []
        remaining = list(outline.chapters)
        total = len(remaining)
        batch_num = 0

        while remaining:
            # Find all chapters whose dependencies are satisfied
            ready = [
                ch for ch in remaining
                if all(dep in completed for dep in ch.depends_on)
            ]
            if not ready:
                # Cycle or unresolvable deps — force-unblock by taking the first remaining
                logger.warning(
                    f"[Orchestrator] Dependency cycle detected, force-unblocking: "
                    f"{[ch.chapter_id for ch in remaining]}"
                )
                ready = [remaining[0]]

            batch_num += 1
            logger.info(
                f"[Orchestrator] Batch {batch_num}: executing {[ch.chapter_id for ch in ready]} "
                f"({len(completed)}/{total} done)"
            )
            self._emit("status", {
                "message": f"正在撰写章节（{len(completed)}/{total}）...",
                "stage": "chapters",
                "progress": 30 + int(len(completed) / total * 20),
            })

            # Execute ready batch in parallel, passing accumulated predecessor contents
            batch_results = await asyncio.gather(
                *[self._execute_single_chapter(ch, session_dir, completed_contents) for ch in ready],
                return_exceptions=True,
            )

            for ch, result in zip(ready, batch_results):
                if isinstance(result, Exception):
                    logger.error(f"[Orchestrator] Chapter {ch.chapter_id} failed: {result}")
                    finding = Finding(
                        task_id=ch.chapter_id,
                        role="chapter_writer",
                        summary=f"{ch.title}: 生成失败",
                        details={"chapter_id": ch.chapter_id, "title": ch.title, "error": str(result)},
                        confidence=0.0,
                    )
                    # Use empty file path on failure (worker creates the path)
                    file_path = session_dir / f"chapter_{ch.chapter_id}.md"
                else:
                    file_path, finding = result

                chapter_files.append(file_path)
                chapter_findings.append(finding)
                completed.add(ch.chapter_id)

                # Cache chapter content for downstream dependency injection
                if file_path.exists():
                    try:
                        completed_contents[ch.chapter_id] = file_path.read_text(encoding="utf-8")
                    except Exception as e:
                        logger.warning(f"[Orchestrator] Failed to read chapter {ch.chapter_id} for dependency cache: {e}")

            remaining = [ch for ch in remaining if ch.chapter_id not in completed]

        self._emit("status", {"message": f"已完成 {len(chapter_files)} 个章节的撰写", "stage": "chapters", "progress": 50})

        # --- Step 3: Run revision loops in parallel across all chapters ---
        self._emit("status", {"message": "正在审校各章节质量...", "stage": "chapters", "progress": 55})
        logger.info(f"[Orchestrator] Running revision loops for {len(chapter_files)} chapters")
        t0 = time.perf_counter()

        workers_for_revision = [
            ChapterWorker(
                chapter_outline=ch,
                session_dir=session_dir,
                trace_id=trace_id,
                document_collection=self.document_collection,
                document_ids=self.document_ids,
                documents_only=self.documents_only,
            )
            for ch in outline.chapters
        ]
        revision_tasks = [
            self.reviser.revision_loop(
                chapter_outline=ch,
                chapter_file=f,
                worker=w,
            )
            for ch, f, w in zip(outline.chapters, chapter_files, workers_for_revision)
        ]
        revision_results = await asyncio.gather(*revision_tasks, return_exceptions=True)
        logger.info(f"[Orchestrator] All revision loops done in {time.perf_counter()-t0:.2f}s")

        for result, finding in zip(revision_results, chapter_findings):
            if isinstance(result, Exception):
                logger.error(f"[Orchestrator] Revision for {finding.task_id} failed: {result}")
                finding.details["review_passed"] = False
            else:
                finding.details["review_passed"] = result

        # Re-extract sources from final chapter files (revision may have changed citations)
        for f_path, finding in zip(chapter_files, chapter_findings):
            if f_path.exists():
                finding.sources = _extract_sources_from_text(f_path.read_text(encoding="utf-8"))

        return chapter_files, chapter_findings

    async def _execute_single_chapter(
        self,
        chapter: ChapterOutline,
        session_dir: Path,
        completed_contents: dict[str, str],
    ) -> tuple[Path, Finding]:
        """Execute a single chapter: create worker, write, return file and finding."""
        trace_id = getattr(self, "_trace_id", None)

        # Filter predecessor contents by chapter.depends_on
        dependency_contents: dict[str, str] = {}
        for dep_id in chapter.depends_on:
            if dep_id in completed_contents:
                dependency_contents[dep_id] = completed_contents[dep_id]
            else:
                logger.warning(
                    f"[Orchestrator] Chapter {chapter.chapter_id} depends on {dep_id} "
                    "but content not yet available"
                )

        worker = ChapterWorker(
            chapter_outline=chapter,
            session_dir=session_dir,
            trace_id=trace_id,
            document_collection=self.document_collection,
            document_ids=self.document_ids,
            dependency_contents=dependency_contents,
            documents_only=self.documents_only,
        )
        finding = await worker.execute()
        return worker.chapter_file, finding

    async def _handle_clarification_response(
        self,
        user_response: str,
    ) -> AgentMessage:
        """Handle user's response to a clarification prompt."""
        if self._clarification_result is None:
            return AgentMessage.create_error(
                sender=self.name,
                receiver="user",
                error_message="No active clarification session",
            )

        prev = self._clarification_result
        result = await self.intent_clarifier.incorporate_response(
            original_query=prev.original_query,
            clarification_question=prev.clarification_question,
            user_response=user_response,
            existing_plan_brief=prev.plan_brief,
        )
        self._total_clarification_rounds += 1

        # Build enriched_query from plan_brief for backward compatibility
        enriched_query = (
            result.plan_brief.to_prompt_block()
            if result.plan_brief
            else prev.original_query
        )
        logger.debug(f"[Orchestrator] Clarified plan: {enriched_query[:100]}...")

        self.memory.session.clarification_state = {
            "status": "completed",
            "rounds": self._total_clarification_rounds,
            "enriched_query": enriched_query,
        }
        await self.memory.save()
        self._clarification_result = None
        self._confirmed_plan_brief = result.plan_brief
        return await self._execute_research(
            enriched_query, prev.original_query, plan_brief=result.plan_brief
        )

    def _build_sections_from_chapters(self, chapter_files: list[Path]) -> dict[str, str]:
        """Build sections dict from chapter files for report metadata."""
        sections: dict[str, str] = {}
        for f in chapter_files:
            if f.exists():
                content = f.read_text(encoding="utf-8")
                # Extract chapter title from first ## heading
                title = f.stem  # e.g., "chapter_c1"
                sections[title] = content
        return sections

    def _build_document_hint(self) -> str:
        """Return a system hint describing the user's uploaded documents (or "")."""
        if not self.document_collection:
            return ""

        try:
            from deep_research.rag.pipeline import RAGPipeline

            pipeline = RAGPipeline(collection_name=self.document_collection)
            docs = pipeline.list_documents()
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[Orchestrator] failed to list uploaded docs: {e}")
            return ""

        if self.document_ids:
            allowed = set(self.document_ids)
            docs = [d for d in docs if d.get("doc_id") in allowed]

        if not docs:
            return ""

        names = "、".join(d.get("filename") or d.get("doc_id") or "?" for d in docs[:10])
        return (
            f"【用户已上传 {len(docs)} 份参考文档】{names}\n"
            f"撰写时请优先使用 document_search 工具检索这些文档中的内容作为研究依据，"
            f"必要时再结合联网搜索补充背景信息。引用文档时使用 [来源: 文件名] 格式。"
        )
