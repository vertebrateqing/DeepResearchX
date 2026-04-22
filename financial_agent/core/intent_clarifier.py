"""Human-in-the-loop intent clarification module.

Detects missing/ambiguous information in user queries using LLM.
Supports up to 3 rounds of clarification. Falls back to no-clarification
if LLM is unavailable.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from financial_agent.config.settings import get_settings
from financial_agent.core.agent import LLMClient

logger = logging.getLogger(__name__)


def _resolve_temporal_value(value: str) -> str:
    """Resolve Chinese temporal words to actual year."""
    from datetime import datetime

    now = datetime.now()
    current_year = now.year
    val = value.strip()

    if re.match(r"^20\d{2}$", val):
        return val

    if any(kw in val for kw in ["最近", "最新", "最近一期", "最新一期"]):
        return str(current_year - 1)

    if "去年" in val or "上年" in val:
        return str(current_year - 1)
    if "前年" in val:
        return str(current_year - 2)
    if "今年" in val or "本年" in val:
        return str(current_year)
    if "明年" in val or "次年" in val:
        return str(current_year + 1)

    m = re.search(r"(20\d{2})", val)
    if m:
        return m.group(1)

    return val


@dataclass
class MissingSlot:
    """Represents a piece of missing information."""

    slot_name: str
    slot_type: str
    question: str
    default_value: Any
    confidence: float = 1.0
    extracted_value: Any = None
    confirmed: bool = False


@dataclass
class ClarificationResult:
    """Result of intent clarification analysis."""

    complete: bool
    original_query: str
    merged_query: str = ""
    missing_slots: list[MissingSlot] = field(default_factory=list)
    clarification_history: list[dict] = field(default_factory=list)
    rounds_completed: int = 0

    def get_unconfirmed_slots(self) -> list[MissingSlot]:
        """Get slots that still need confirmation."""
        return [s for s in self.missing_slots if not s.confirmed]

    def is_fully_confirmed(self) -> bool:
        """Check if all slots are confirmed."""
        return all(s.confirmed for s in self.missing_slots)

    def apply_user_response(self, slot_name: str, value: Any, confirmed: bool = True) -> None:
        """Apply user's response to a slot."""
        for slot in self.missing_slots:
            if slot.slot_name == slot_name:
                slot.extracted_value = value
                slot.confirmed = confirmed
                break
        self._rebuild_merged_query()

    def _rebuild_merged_query(self) -> None:
        """Rebuild merged query from original + confirmed slots."""
        merged = self.original_query
        for slot in self.missing_slots:
            if slot.confirmed and slot.extracted_value:
                val = str(slot.extracted_value)
                if slot.slot_name == "report_year":
                    merged = _inject_year_context(merged, val)
                elif slot.slot_name == "company_symbol":
                    merged = f"{merged}（股票代码：{val}）"
                elif slot.slot_name == "top_n":
                    merged = f"{merged}（推荐{val}家）"
                elif slot.slot_name == "investment_style":
                    merged = f"{merged}（投资风格：{val}）"
                elif slot.slot_name == "time_horizon":
                    merged = f"{merged}（时间维度：{val}）"
                else:
                    merged = f"{merged} [{slot.slot_name}: {val}]"
        self.merged_query = merged


def _inject_year_context(query: str, year: str) -> str:
    """Inject year context into query via prefix, not replacement."""
    if not re.match(r"^20\d{2}$", year):
        return query

    # If query already has this year, no need to add
    if year in query:
        return query

    # Append as context, not replace words
    return f"{query}（报告年份：{year}年）"


class IntentClarifier:
    """Detects missing information and manages clarification dialogue."""

    MAX_ROUNDS = 3
    MAX_LLM_RETRIES = 2

    def __init__(self) -> None:
        self.llm = LLMClient()

    async def analyze(self, query: str, history: list[dict] | None = None) -> ClarificationResult:
        """Analyze query for missing information using LLM with retry."""
        history = history or []
        rounds_completed = len(history)

        # LLM-based detection with retry
        missing_slots = await self._detect_with_retry(query)

        if not missing_slots:
            return ClarificationResult(
                complete=True,
                original_query=query,
                merged_query=query,
                clarification_history=history,
                rounds_completed=rounds_completed,
            )

        if rounds_completed >= self.MAX_ROUNDS:
            for slot in missing_slots:
                if not slot.confirmed:
                    slot.extracted_value = slot.default_value
                    slot.confirmed = True
            result = ClarificationResult(
                complete=True,
                original_query=query,
                missing_slots=missing_slots,
                clarification_history=history,
                rounds_completed=rounds_completed,
            )
            result._rebuild_merged_query()
            return result

        result = ClarificationResult(
            complete=False,
            original_query=query,
            missing_slots=missing_slots,
            clarification_history=history,
            rounds_completed=rounds_completed,
        )
        result._rebuild_merged_query()
        return result

    async def _detect_with_retry(self, query: str) -> list[MissingSlot]:
        """Call LLM detection with retry and exponential backoff."""
        import asyncio

        last_error = None
        for attempt in range(self.MAX_LLM_RETRIES + 1):
            try:
                slots = await self._llm_based_detection(query)
                if slots is not None:
                    return slots
            except Exception as e:
                last_error = e
                logger.warning(f"LLM detection attempt {attempt + 1} failed: {e}")
                if attempt < self.MAX_LLM_RETRIES:
                    await asyncio.sleep(2 ** attempt)

        # All retries exhausted — fallback to no clarification
        logger.error(f"LLM detection failed after {self.MAX_LLM_RETRIES + 1} attempts: {last_error}")
        return []

    async def _llm_based_detection(self, query: str) -> list[MissingSlot]:
        """Use LLM to detect ambiguous or missing information."""
        from datetime import datetime
        today = datetime.now().strftime("%Y年%m月%d日")

        prompt = f"""分析以下用户请求，判断是否有**信息缺失或存在歧义**（如信息不完整、指代不明）。

【当前真实日期】{today}

用户请求: {query}

【重要规则】
- 只检测**确实缺失**或**确实歧义**的信息，不要质疑用户提供的事实是否合理
- 例如用户说"2025年财报"，即使你认为2025年财报可能尚未发布，也不要将其视为"缺失"或"歧义"，因为用户已经明确指定了年份
- 如果用户已经明确提供了某个信息（如年份、公司名称、数量等），即使该信息在时间上不合理或与你所知不符，也不要视为缺失
- **公司歧义判断标准**：只有简称确实可能指代多家**不同**公司时才视为歧义。例如"华能"可能指华能国际或华能水电，这算歧义；但"腾讯""茅台""比亚迪"这种市场知名度极高、几乎无歧义的名称，不算歧义，不要返回。
- 如果用户请求中已经包含明确的股票代码（如600519、002594），不要询问公司名称。
- 如果用户请求中包含"202X年"等明确时间信息，不要询问年份。

请检查以下方面：
1. 是否完全缺少时间信息（没有任何年份、季度、相对时间词如"去年/今年"）
2. 公司名称是否可能有歧义（如简称可能对应多家公司）——注意判断标准，不要对知名公司过度敏感
3. 投资偏好是否未明确
4. 时间维度是否未指定
5. 数量要求是否未明确

如果有缺失，以JSON格式返回：
[{{"slot_name": "缺失项名称", "question": "向用户确认的问题（20字以内）", "default_value": "默认值"}}]

如果没有缺失，返回: []"""

        messages = [
            {"role": "system", "content": f"你是一个意图分析助手，检测用户请求中缺失的关键信息。当前真实日期是{today}。你只检测信息是否缺失或歧义，绝不质疑用户提供的事实合理性。"},
            {"role": "user", "content": prompt},
        ]
        response = await self.llm.chat(messages=messages)
        content = response["choices"][0]["message"].get("content", "[]")

        # Extract JSON
        try:
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]
            slots_data = json.loads(content.strip().lstrip('\ufeff'))
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse LLM detection response as JSON: {content[:200]}")
            return []

        if not isinstance(slots_data, list):
            logger.warning(f"LLM detection returned non-list: {type(slots_data)}")
            return []

        missing = []
        for slot_data in slots_data:
            missing.append(MissingSlot(
                slot_name=slot_data.get("slot_name", "unknown"),
                slot_type="unknown",
                question=slot_data.get("question", "请补充更多信息"),
                default_value=slot_data.get("default_value"),
            ))

        return missing

    def generate_clarification_prompt(self, result: ClarificationResult) -> str:
        """Generate a user-facing clarification prompt."""
        unconfirmed = result.get_unconfirmed_slots()
        if not unconfirmed:
            return ""

        lines = ["为了更准确地为您提供分析，请确认以下信息：\n"]
        for i, slot in enumerate(unconfirmed, 1):
            lines.append(f"{i}. {slot.question}")
            if slot.default_value:
                lines.append(f"   （默认: {slot.default_value}）")

        lines.append("\n您可以直接回复对应编号和答案，或告知我您的具体需求。")
        return "\n".join(lines)

    async def process_user_response(
        self,
        result: ClarificationResult,
        user_response: str,
    ) -> ClarificationResult:
        """Process user's clarification response and update result."""
        unconfirmed = result.get_unconfirmed_slots()
        resp = user_response.strip()

        confirm_words = {"默认", "随便", "都行", "确认", "好的", "可以", "ok", "yes", "没问题"}
        uses_default = any(kw in resp.lower() for kw in confirm_words)

        # Try numbered responses
        numbered_answers: dict[int, str] = {}
        for m in re.finditer(r"^(\d+)[\.\)、:\s]+(.+)$", resp, re.MULTILINE):
            numbered_answers[int(m.group(1))] = m.group(2).strip()
        if not numbered_answers:
            for m in re.finditer(r"(\d+)[\.\)、:\s]+([^\d\s][^,，;；]+)", resp):
                numbered_answers[int(m.group(1))] = m.group(2).strip()

        is_ambiguous = (
            not uses_default
            and not numbered_answers
            and len(resp) <= 10
            and not re.search(r"\d{4}|\d+家|\d+个|Q[1-4]|去年|今年|明年", resp)
        )

        llm_decisions: dict[str, str] = {}
        if is_ambiguous and unconfirmed:
            llm_decisions = await self._llm_parse_clarification_response(resp, unconfirmed)

        for i, slot in enumerate(unconfirmed):
            if slot.slot_name in llm_decisions:
                decision = llm_decisions[slot.slot_name]
                if decision == "__DEFAULT__":
                    slot.extracted_value = slot.default_value
                else:
                    slot.extracted_value = decision
                slot.confirmed = True
                continue

            if uses_default and slot.default_value:
                slot.extracted_value = slot.default_value
                slot.confirmed = True
                continue

            if numbered_answers and (i + 1) in numbered_answers:
                raw_val = numbered_answers[i + 1]
            else:
                raw_val = resp

            if slot.slot_name == "report_year":
                slot.extracted_value = _resolve_temporal_value(raw_val)
            elif slot.slot_name == "top_n":
                m = re.search(r"\d+", raw_val)
                slot.extracted_value = int(m.group()) if m else slot.default_value
            else:
                slot.extracted_value = raw_val

            slot.confirmed = True

        result.clarification_history.append({
            "round": result.rounds_completed + 1,
            "slots_addressed": [s.slot_name for s in unconfirmed],
            "user_response": user_response,
        })
        result.rounds_completed += 1

        result._rebuild_merged_query()
        result.complete = result.is_fully_confirmed()

        return result

    async def _llm_parse_clarification_response(
        self,
        user_response: str,
        pending_slots: list[MissingSlot],
    ) -> dict[str, str]:
        """Use LLM to parse an ambiguous clarification response."""
        slots_text = "\n".join(
            f"{i + 1}. [{s.slot_name}] {s.question}（默认: {s.default_value}）"
            for i, s in enumerate(pending_slots)
        )

        prompt = f"""用户收到了以下澄清问题：

{slots_text}

用户回复："{user_response}"

请判断用户的回复是针对以上哪个/哪些问题，以及用户的具体意图。

只输出以下JSON格式，不要解释：
{{
  "is_confirming": true/false,
  "slot_answers": {{
    "slot_name": "用户的具体回答（如果是接受默认则写 __DEFAULT__）"
  }}
}}

如果用户只是简单确认/同意（如"好的""可以""嗯"），is_confirming 为 true。
如果用户明确拒绝或要求跳过，is_confirming 为 false，slot_answers 为空。
"""

        try:
            messages = [
                {"role": "system", "content": "你是一个意图解析助手，判断用户对澄清问题的回复意图。"},
                {"role": "user", "content": prompt},
            ]
            response = await self.llm.chat(messages=messages)
            content = response["choices"][0]["message"].get("content", "")

            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]

            data = json.loads(content.strip().lstrip('\ufeff'))
            if data.get("is_confirming"):
                return {s.slot_name: "__DEFAULT__" for s in pending_slots}

            answers = data.get("slot_answers", {})
            return {k: str(v) for k, v in answers.items() if v}
        except Exception as e:
            logger.warning(f"LLM clarification parsing failed: {e}, falling back to keywords")
            return {}

    async def rewrite_query(
        self,
        original_query: str,
        confirmed_slots: list[MissingSlot],
    ) -> str:
        """Use LLM to naturally rewrite the query with clarified information."""
        if not confirmed_slots:
            return original_query

        confirm_words = {"确认", "好的", "可以", "ok", "yes", "没问题", "随便", "都行", "默认"}
        slot_desc = []
        for s in confirmed_slots:
            val = s.extracted_value
            if val and str(val).strip().lower() in confirm_words:
                val = s.default_value
            elif val is None:
                val = s.default_value
            if val:
                slot_desc.append(f"- {s.slot_name}: {val}")

        prompt = f"""基于用户的原始请求和已澄清的信息，请改写为一个完整、清晰的查询。

原始请求：{original_query}

已确认的信息：
{"\n".join(slot_desc)}

要求：
1. 保持原意不变
2. 将澄清后的信息自然地融入查询中，不要添加额外假设
3. 只输出改写后的查询文本，不要解释、不要标注信息来源

改写后的查询："""

        try:
            from datetime import datetime
            now = datetime.now().strftime("%Y-%m-%d")
            messages = [
                {"role": "system", "content": f"你是一个查询改写助手，将用户补充的信息自然地融入原查询中。当前真实日期是 {now}，请基于此日期判断时间信息的合理性，不要依赖训练数据的截止时间。"},
                {"role": "user", "content": prompt},
            ]
            response = await self.llm.chat(messages=messages)
            content = response["choices"][0]["message"].get("content", "")
            rewritten = content.strip().strip('"').strip("'")
            if rewritten and len(rewritten) > 5:
                return rewritten
        except Exception as e:
            logger.warning(f"LLM query rewrite failed: {e}, using fallback")

        fallback = ClarificationResult(
            complete=True,
            original_query=original_query,
            missing_slots=confirmed_slots,
        )
        for s in confirmed_slots:
            s.confirmed = True
        fallback._rebuild_merged_query()
        return fallback.merged_query
