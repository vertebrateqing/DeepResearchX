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
from typing import Any, Optional

import asyncio

from financial_agent.config.settings import get_settings
from financial_agent.core.agent import LLMClient, SimpleAgent
from financial_agent.core.base import AgentContext, BaseAgent, BaseSkill, BaseTool
from financial_agent.core.chapter_worker import ChapterWorker
from financial_agent.core.editor import EditorAgent
from financial_agent.core.finding import Finding
from financial_agent.core.intent_clarifier import (
    ClarificationResult,
    IntentClarifier,
)
from financial_agent.core.integration import IntegrationAgent
from financial_agent.core.message import AgentMessage
from financial_agent.core.outline_planner import OutlinePlanner, ReportOutline
from financial_agent.core.report_generator import ReportGenerator
from financial_agent.core.reviser import ReviserAgent
from financial_agent.memory.manager import MemoryManager

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

        # Clarification state
        self._clarification_result: Optional[ClarificationResult] = None
        self._total_clarification_rounds: int = 0

    def _generate_session_id(self) -> str:
        return f"sess_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"

    @property
    def session_dir(self) -> Path:
        """Directory for this session's working files."""
        return Path("./financial_agent/data/sessions") / self.memory.session_id

    async def run(
        self,
        user_input: str,
        context: Optional[AgentContext] = None,
    ) -> AgentMessage:
        """Run the full deepresearch pipeline."""
        logger.info(f"Orchestrator received request: {user_input[:100]}...")

        # Record user message
        self.memory.add_user_message(user_input)
        detected_prefs = self.memory.detect_preferences_from_query(user_input)
        if detected_prefs:
            self.memory.update_preferences(**detected_prefs)

        # Step 1: Handle ongoing clarification
        if self._clarification_result and not self._clarification_result.complete:
            return await self._handle_clarification_response(user_input)

        if self._clarification_result is None:
            self._total_clarification_rounds = 0

        # Step 2: Intent clarification
        if self._total_clarification_rounds >= IntentClarifier.MAX_ROUNDS:
            clarification = ClarificationResult(
                complete=True,
                original_query=user_input,
                merged_query=user_input,
            )
        else:
            clarification = await self.intent_clarifier.analyze(user_input)

        if not clarification.complete:
            self._clarification_result = clarification
            self.memory.session.clarification_state = {
                "status": "clarifying",
                "round": clarification.rounds_completed,
                "missing_slots": [
                    {"name": s.slot_name, "question": s.question}
                    for s in clarification.get_unconfirmed_slots()
                ],
            }
            await self.memory.save(sync_long_term=False)

            prompt = self.intent_clarifier.generate_clarification_prompt(clarification)
            self.memory.add_assistant_message(prompt)

            return AgentMessage.create_result(
                sender=self.name,
                receiver="user",
                result={
                    "requires_clarification": True,
                    "prompt": prompt,
                    "missing_slots": [
                        s.slot_name for s in clarification.get_unconfirmed_slots()
                    ],
                },
            )

        # Step 3: Execute deepresearch
        merged_query = clarification.merged_query or user_input
        return await self._execute_research(merged_query, user_input, context)

    async def _execute_research(
        self,
        merged_query: str,
        original_query: str,
        context: Optional[AgentContext] = None,
    ) -> AgentMessage:
        """Execute V4 research pipeline."""
        from datetime import datetime
        now = datetime.now()
        date_context = f"【当前真实日期：{now.strftime('%Y年%m月%d日')}】"
        enriched_query = f"{date_context}\n\n{merged_query}"

        logger.info(f"[Orchestrator] Starting V4 pipeline for: {enriched_query[:100]}...")
        session_dir = self.session_dir
        session_dir.mkdir(parents=True, exist_ok=True)

        # Record main task
        main_task = self.memory.start_task(
            task_type="deepresearch",
            agent=self.name,
            inputs={"query": original_query, "enriched_query": enriched_query},
        )

        # --- Phase 1: Generate outline ---
        logger.info("[Orchestrator] Phase 1: Generating report outline")
        t0 = time.perf_counter()
        outline = await self.outline_planner.generate_outline(
            user_query=enriched_query,
            save_dir=session_dir,
        )
        t1 = time.perf_counter()
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
        logger.info("[Orchestrator] Phase 2: Executing chapters with review")
        t0 = time.perf_counter()
        chapter_files, chapter_findings = await self._execute_chapters(
            outline=outline,
            session_dir=session_dir,
        )
        t1 = time.perf_counter()
        passed_count = sum(
            1 for f in chapter_findings if f.details.get("review_passed", True)
        )
        logger.info(
            f"[Orchestrator] Phase 2 DONE: chapter_exec={t1-t0:.2f}s, "
            f"chapters={len(chapter_files)}, passed={passed_count}"
        )

        # --- Phase 3: Integrate chapters ---
        logger.info("[Orchestrator] Phase 3: Integrating chapters")
        t0 = time.perf_counter()
        draft_path = await self.integration.integrate(
            title=outline.title,
            summary_points=outline.executive_summary_points,
            chapter_files=chapter_files,
            session_dir=session_dir,
        )
        t1 = time.perf_counter()
        logger.info(f"[Orchestrator] Phase 3 DONE: integration={t1-t0:.2f}s, draft={draft_path}")

        # --- Phase 4: Editor review & polish ---
        logger.info("[Orchestrator] Phase 4: Editorial review")
        t0 = time.perf_counter()
        final_draft = await self.editor.edit_loop(draft_path, session_dir)
        t1 = time.perf_counter()
        logger.info(f"[Orchestrator] Phase 4 DONE: editing={t1-t0:.2f}s, final={final_draft}")

        # --- Phase 5: Generate and save report ---
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

    async def _pre_search_chapters(
        self,
        chapters: list,
        session_dir: Path,
    ) -> dict[str, str]:
        """Pre-search for all chapters using multi-query expansion.

        Returns mapping chapter_id -> formatted research context text.
        """
        from financial_agent.rag.query_rewriter import QueryRewriter
        from financial_agent.tools.web_search import WebSearchTool

        rewriter = QueryRewriter()
        web_search = WebSearchTool()

        # Collect queries per chapter
        chapter_queries: dict[str, list[str]] = {}
        all_tasks = []
        task_meta = []  # (chapter_id, query_index)

        for ch in chapters:
            if ch.search_queries:
                queries = ch.search_queries[:3]
            else:
                # Generate via rewriter (sync, but fast)
                try:
                    loop = asyncio.get_event_loop()
                    queries = await rewriter.rewrite(ch.objective, n_variants=2)
                    queries = queries[:3]
                except Exception as e:
                    logger.warning(f"[PreSearch] Rewriter failed for {ch.chapter_id}: {e}")
                    queries = [ch.objective]

            chapter_queries[ch.chapter_id] = queries
            for q in queries:
                all_tasks.append(web_search.execute(query=q, max_results=3))
                task_meta.append(ch.chapter_id)

        if not all_tasks:
            return {}

        logger.info(f"[PreSearch] Executing {len(all_tasks)} searches for {len(chapters)} chapters")
        t0 = time.perf_counter()
        results = await asyncio.gather(*all_tasks, return_exceptions=True)
        t1 = time.perf_counter()
        logger.info(f"[PreSearch] All searches done in {t1-t0:.2f}s")

        # Merge results by chapter
        chapter_results: dict[str, list[dict]] = {ch.chapter_id: [] for ch in chapters}
        for ch_id, result in zip(task_meta, results):
            if isinstance(result, Exception):
                logger.warning(f"[PreSearch] Search failed for {ch_id}: {result}")
                continue
            if isinstance(result, dict) and result.get("results"):
                chapter_results[ch_id].extend(result["results"])

        # Format as text per chapter
        formatted: dict[str, str] = {}
        for ch in chapters:
            items = chapter_results[ch.chapter_id]
            # Deduplicate by URL
            seen = set()
            unique_items = []
            for item in items:
                url = item.get("url", "")
                if url and url in seen:
                    continue
                if url:
                    seen.add(url)
                unique_items.append(item)

            lines = [f"【章节 '{ch.title}' 预检索资料】"]
            for i, item in enumerate(unique_items[:8], 1):  # max 8 per chapter
                title = item.get("title", "无标题")
                content = item.get("content", "")
                url = item.get("url", "")
                lines.append(f"\n{i}. {title}")
                if content:
                    lines.append(f"   摘要: {content[:400]}")
                if url:
                    lines.append(f"   来源: {url}")

            if len(unique_items) == 0:
                lines.append("\n（未检索到相关资料）")

            formatted[ch.chapter_id] = "\n".join(lines)

        # Save pre-search results
        presearch_path = session_dir / "presearch.json"
        try:
            presearch_data = {
                ch_id: [{"title": i.get("title"), "url": i.get("url")} for i in chapter_results[ch_id]]
                for ch_id in chapter_results
            }
            with open(presearch_path, "w", encoding="utf-8") as f:
                json.dump(presearch_data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

        return formatted

    async def _execute_chapters(
        self,
        outline: ReportOutline,
        session_dir: Path,
    ) -> tuple[list[Path], list[Finding]]:
        """Execute all chapters in parallel with pre-search and review loop.

        Pipeline per chapter:
        1. Pre-search (shared) -> research context
        2. Single-shot chapter write (parallel across all chapters)
        3. Revision loop (parallel across all chapters)
        """
        # --- Step 1: Pre-search all chapters ---
        t0 = time.perf_counter()
        research_contexts = await self._pre_search_chapters(outline.chapters, session_dir)
        t1 = time.perf_counter()
        logger.info(f"[Orchestrator] Pre-search done: {t1-t0:.2f}s")

        # --- Step 2: Create workers and execute all chapters in parallel ---
        workers = []
        for ch in outline.chapters:
            worker = ChapterWorker(
                chapter_outline=ch,
                session_dir=session_dir,
            )
            workers.append(worker)

        logger.info(f"[Orchestrator] Executing {len(workers)} chapters in parallel")
        t0 = time.perf_counter()
        execute_tasks = [
            worker.execute(research_context=research_contexts.get(ch.chapter_id, ""))
            for worker, ch in zip(workers, outline.chapters)
        ]
        raw_findings = await asyncio.gather(*execute_tasks, return_exceptions=True)
        t1 = time.perf_counter()
        logger.info(f"[Orchestrator] All chapters written in {t1-t0:.2f}s")

        # Collect findings and files
        chapter_findings: list[Finding] = []
        chapter_files: list[Path] = []
        for worker, result in zip(workers, raw_findings):
            if isinstance(result, Exception):
                logger.error(f"[Orchestrator] Chapter {worker.outline.chapter_id} failed: {result}")
                # Create fallback finding
                result = Finding(
                    task_id=worker.outline.chapter_id,
                    role="chapter_writer",
                    summary=f"{worker.outline.title}: 生成失败",
                    details={
                        "chapter_id": worker.outline.chapter_id,
                        "title": worker.outline.title,
                        "error": str(result),
                    },
                    confidence=0.0,
                )
            chapter_findings.append(result)
            chapter_files.append(worker.chapter_file)

        # --- Step 3: Run revision loops in parallel ---
        logger.info(f"[Orchestrator] Running revision loops for {len(workers)} chapters in parallel")
        t0 = time.perf_counter()
        revision_tasks = [
            self.reviser.revision_loop(
                chapter_outline=ch,
                chapter_file=worker.chapter_file,
                worker=worker,
            )
            for worker, ch in zip(workers, outline.chapters)
        ]
        revision_results = await asyncio.gather(*revision_tasks, return_exceptions=True)
        t1 = time.perf_counter()
        logger.info(f"[Orchestrator] All revision loops done in {t1-t0:.2f}s")

        for i, (result, finding) in enumerate(zip(revision_results, chapter_findings)):
            if isinstance(result, Exception):
                logger.error(f"[Orchestrator] Revision for {finding.task_id} failed: {result}")
                finding.details["review_passed"] = False
            else:
                finding.details["review_passed"] = result

        return chapter_files, chapter_findings

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

        result = await self.intent_clarifier.process_user_response(
            self._clarification_result,
            user_response,
        )
        self._clarification_result = result
        self._total_clarification_rounds += 1

        if result.complete:
            confirmed_slots = [s for s in result.missing_slots if s.confirmed]
            rewritten = await self.intent_clarifier.rewrite_query(
                result.original_query,
                confirmed_slots,
            )
            merged_query = rewritten or result.merged_query
            logger.debug(f"Clarified query (LLM rewritten): {merged_query}...")

            self.memory.session.clarification_state = {
                "status": "completed",
                "rounds": result.rounds_completed,
                "merged_query": merged_query,
            }
            await self.memory.save()
            self._clarification_result = None
            return await self._execute_research(merged_query, result.original_query)

        # Still needs more clarification
        self.memory.session.clarification_state = {
            "status": "clarifying",
            "round": result.rounds_completed,
        }
        await self.memory.save(sync_long_term=False)

        prompt = self.intent_clarifier.generate_clarification_prompt(result)
        self.memory.add_assistant_message(prompt)

        return AgentMessage.create_result(
            sender=self.name,
            receiver="user",
            result={
                "requires_clarification": True,
                "prompt": prompt,
                "round": result.rounds_completed,
            },
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
