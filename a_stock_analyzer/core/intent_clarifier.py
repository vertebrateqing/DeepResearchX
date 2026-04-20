"""Human-in-the-loop intent clarification module.

Detects missing/ambiguous information in user queries and generates
clarification questions. Supports up to 3 rounds of clarification.
User must confirm before proceeding; if not confirmed, continues interaction
until intent is fully clear.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from a_stock_analyzer.config.settings import get_settings
from a_stock_analyzer.core.agent import LLMClient

logger = logging.getLogger(__name__)


@dataclass
class MissingSlot:
    """Represents a piece of missing information."""

    slot_name: str
    slot_type: str  # "temporal", "entity", "preference", "numeric", "scope"
    question: str
    default_value: Any
    confidence: float = 1.0
    extracted_value: Any = None  # value extracted from user response
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

        # Rebuild merged query
        self._rebuild_merged_query()

    def _rebuild_merged_query(self) -> None:
        """Rebuild merged query from original + confirmed slots."""
        parts = [self.original_query]
        for slot in self.missing_slots:
            if slot.confirmed and slot.extracted_value:
                parts.append(f"[{slot.slot_name}: {slot.extracted_value}]")
        self.merged_query = " ".join(parts)


# Predefined clarification rules
CLARIFICATION_RULES = [
    {
        "name": "report_year",
        "slot_name": "report_year",
        "slot_type": "temporal",
        "patterns": [
            r"财报|年报|季报|半年报|中报",
        ],
        "negative_patterns": [
            r"20\d{2}年",
            r"\d{4}年",
            r"第[一二三四].季度",
            r"Q[1-4]",
        ],
        "question": "请问您想分析哪个年份/季度的财报？",
        "default_value": "最近一期",
    },
    {
        "name": "company_ambiguity",
        "slot_name": "company_symbol",
        "slot_type": "entity",
        "patterns": [
            r"[^\d\W]{2,4}(?:公司|股份|集团|科技)",
        ],
        "negative_patterns": [
            r"\(\d{6}\)",  # has stock code
            r"股票代码",
        ],
        "question": "请确认具体的公司名称或股票代码，避免歧义。",
        "default_value": None,
    },
    {
        "name": "investment_style",
        "slot_name": "investment_style",
        "slot_type": "preference",
        "patterns": [
            r"推荐.*(?:股票|公司|买)",
            r"(?:值得|可以|适合).*投资",
        ],
        "negative_patterns": [
            r"稳健|保守|价值|成长|激进|高风险",
        ],
        "question": "您偏好哪种投资风格？（稳健型/价值型/成长型/激进型）",
        "default_value": "均衡型",
    },
    {
        "name": "time_horizon",
        "slot_name": "time_horizon",
        "slot_type": "scope",
        "patterns": [
            r"(?:近期|短期|中期|长期|现在|未来).*(?:投资|持有|关注)",
            r"(?:看|分析|推荐).*?(?:多久|多长时间)",
        ],
        "negative_patterns": [
            r"1个月|3个月|半年|1年|长期持有",
        ],
        "question": "您关注的时间维度是？（短期1-3个月/中期半年/长期1年以上）",
        "default_value": "中期",
    },
    {
        "name": "top_n_count",
        "slot_name": "top_n",
        "slot_type": "numeric",
        "patterns": [
            r"top.*(?:公司|股票|行业)",
            r"推荐.*(?:几家|几个|多少)",
        ],
        "negative_patterns": [
            r"top\s*\d+",
            r"\d+\s*(?:家|个|只)",
        ],
        "question": "您希望推荐多少家公司/行业？",
        "default_value": 10,
    },
    {
        "name": "company_name_short",
        "slot_name": "company_symbol",
        "slot_type": "entity",
        "patterns": [
            r"^[A-Z]{2,4}$",  # Short uppercase like BYD, CATL
            r"^[^\d\W]{2,3}$",  # Short Chinese names
        ],
        "negative_patterns": [
            r"\(\d{6}\)",
            r"股票代码",
        ],
        "question": "请确认 '{match}' 具体指哪家公司（提供股票代码）？",
        "default_value": None,
    },
]


class IntentClarifier:
    """Detects missing information and manages clarification dialogue."""

    MAX_ROUNDS = 3

    def __init__(self) -> None:
        self.llm = LLMClient()

    async def analyze(self, query: str, history: list[dict] | None = None) -> ClarificationResult:
        """Analyze query for missing information.

        Args:
            query: User's query
            history: Previous clarification rounds

        Returns:
            ClarificationResult with missing slots or complete=True
        """
        history = history or []
        rounds_completed = len(history)

        # Use rule-based detection first
        missing_slots = self._rule_based_detection(query)

        # Use LLM for additional detection if rule-based found nothing
        if not missing_slots:
            missing_slots = await self._llm_based_detection(query)

        if not missing_slots:
            return ClarificationResult(
                complete=True,
                original_query=query,
                merged_query=query,
                clarification_history=history,
                rounds_completed=rounds_completed,
            )

        # Check if we've exceeded max rounds
        if rounds_completed >= self.MAX_ROUNDS:
            # Auto-fill defaults and mark complete
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

    def _rule_based_detection(self, query: str) -> list[MissingSlot]:
        """Detect missing information using predefined rules."""
        missing = []

        for rule in CLARIFICATION_RULES:
            # Check if any positive pattern matches
            matched = False
            for pattern in rule["patterns"]:
                if re.search(pattern, query, re.IGNORECASE):
                    matched = True
                    break

            if not matched:
                continue

            # Check if negative patterns match (information already present)
            has_info = False
            for neg_pattern in rule["negative_patterns"]:
                if re.search(neg_pattern, query, re.IGNORECASE):
                    has_info = True
                    break

            if not has_info:
                question = rule["question"]
                # Format question if it contains {match}
                if "{match}" in question:
                    match = re.search(r"[A-Z]{2,4}", query)
                    if match:
                        question = question.replace("{match}", match.group())

                missing.append(MissingSlot(
                    slot_name=rule["slot_name"],
                    slot_type=rule["slot_type"],
                    question=question,
                    default_value=rule["default_value"],
                ))

        return missing

    async def _llm_based_detection(self, query: str) -> list[MissingSlot]:
        """Use LLM to detect ambiguous or missing information."""
        prompt = f"""分析以下用户请求，判断是否有信息缺失或存在歧义。

用户请求: {query}

请检查以下方面：
1. 是否缺少时间信息（年份、季度）
2. 公司名称是否可能有歧义
3. 投资偏好是否未明确
4. 时间维度是否未指定
5. 数量要求是否未明确

如果有缺失，以JSON格式返回：
[{{"slot_name": "缺失项名称", "question": "向用户确认的问题", "default_value": "默认值"}}]

如果没有缺失，返回: []"""

        try:
            messages = [
                {"role": "system", "content": "你是一个意图分析助手，检测用户请求中缺失的关键信息。"},
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
                slots_data = json.loads(content.strip())
            except json.JSONDecodeError:
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
        except Exception as e:
            logger.warning(f"LLM-based intent detection failed: {e}")
            return []

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

    def process_user_response(
        self,
        result: ClarificationResult,
        user_response: str,
    ) -> ClarificationResult:
        """Process user's clarification response and update result.

        Returns updated ClarificationResult.
        """
        unconfirmed = result.get_unconfirmed_slots()

        # Try to match response to slots
        for slot in unconfirmed:
            # Simple heuristic: check if response contains meaningful content
            if user_response.strip():
                # Check if user is using the default
                if slot.default_value and any(
                    kw in user_response for kw in ["默认", "随便", "都行", "可以"]
                ):
                    slot.extracted_value = slot.default_value
                    slot.confirmed = True
                else:
                    slot.extracted_value = user_response.strip()
                    slot.confirmed = True

        # Record this round
        result.clarification_history.append({
            "round": result.rounds_completed + 1,
            "slots_addressed": [s.slot_name for s in unconfirmed],
            "user_response": user_response,
        })
        result.rounds_completed += 1

        result._rebuild_merged_query()

        # Check if fully clarified
        result.complete = result.is_fully_confirmed()

        return result