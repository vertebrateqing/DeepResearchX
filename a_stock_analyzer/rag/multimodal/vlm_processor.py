"""Vision-Language Model processor for chart and image understanding.

Supports both cloud (GPT-4V) and local (Qwen-VL) models via configuration.
"""

import base64
import json
import logging
from pathlib import Path
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from a_stock_analyzer.config.settings import get_settings

logger = logging.getLogger(__name__)


class VLMProcessor:
    """Process images/charts using Vision-Language Models."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=120)
        return self._client

    async def describe_image(self, image_path: str) -> str:
        """Generate textual description of an image/chart.

        Args:
            image_path: Path to image file

        Returns:
            Natural language description of the image
        """
        provider = self.settings.llm.provider

        if provider == "openai":
            return await self._describe_with_gpt4v(image_path)
        else:
            return await self._describe_with_local_vlm(image_path)

    async def extract_chart_data(self, image_path: str) -> dict[str, Any]:
        """Extract structured data from a chart image.

        Args:
            image_path: Path to chart image

        Returns:
            Dict with chart_type, labels, values, series, trends
        """
        prompt = """分析这张图表，提取结构化数据。

请以JSON格式返回：
{
    "chart_type": "图表类型(bar/line/pie/scatter等)",
    "title": "图表标题",
    "x_axis_label": "X轴标签",
    "y_axis_label": "Y轴标签",
    "x_labels": ["类别1", "类别2", ...],
    "series": [
        {"name": "系列名称", "values": [值1, 值2, ...]}
    ],
    "trends": ["趋势描述1", "趋势描述2"],
    "key_insights": ["关键洞察1", "关键洞察2"]
}"""

        try:
            description = await self._vlm_chat_with_image(image_path, prompt)
            # Extract JSON
            return self._extract_json_from_response(description)
        except Exception as e:
            logger.error(f"Chart extraction failed: {e}")
            return {"error": str(e), "chart_type": "unknown"}

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    async def _describe_with_gpt4v(self, image_path: str) -> str:
        """Describe image using GPT-4V API."""
        # Read and encode image
        with open(image_path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode("utf-8")

        # Determine MIME type
        ext = Path(image_path).suffix.lower()
        mime_types = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
        }
        mime_type = mime_types.get(ext, "image/jpeg")

        url = self.settings.llm.base_url or "https://api.openai.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.settings.llm.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": "gpt-4o",  # GPT-4o supports vision
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "请详细描述这张图片/图表。如果是财务报表中的图表，"
                                "请说明图表类型、关键数据点和趋势。"
                            ),
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{image_data}",
                            },
                        },
                    ],
                }
            ],
            "max_tokens": 1000,
        }

        response = await self.client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        result = response.json()

        return result["choices"][0]["message"].get("content", "")

    async def _describe_with_local_vlm(self, image_path: str) -> str:
        """Describe image using local VLM (e.g., Qwen-VL)."""
        try:
            # Try to use transformers for local VLM
            from transformers import AutoModelForVision2Seq, AutoProcessor

            model_path = getattr(self.settings.llm, "vlm_model_path", "Qwen/Qwen-VL-Chat")

            processor = AutoProcessor.from_pretrained(model_path, trust_remote_code=True)
            model = AutoModelForVision2Seq.from_pretrained(
                model_path,
                trust_remote_code=True,
                device_map="auto",
            )

            query = processor.from_list_format([
                {"image": image_path},
                {"text": "请描述这张图片/图表。如果是财务图表，请说明数据趋势。"},
            ])

            inputs = processor(query, return_tensors="pt").to(model.device)
            outputs = model.generate(**inputs, max_new_tokens=512)
            response = processor.batch_decode(outputs, skip_special_tokens=True)[0]

            return response
        except ImportError:
            logger.warning("Local VLM not available, using OCR fallback")
            return await self._ocr_fallback(image_path)
        except Exception as e:
            logger.error(f"Local VLM failed: {e}")
            return await self._ocr_fallback(image_path)

    async def _vlm_chat_with_image(self, image_path: str, prompt: str) -> str:
        """Send a VLM request with image and custom prompt."""
        provider = self.settings.llm.provider

        if provider == "openai":
            with open(image_path, "rb") as f:
                image_data = base64.b64encode(f.read()).decode("utf-8")

            ext = Path(image_path).suffix.lower()
            mime_types = {
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
            }
            mime_type = mime_types.get(ext, "image/jpeg")

            url = self.settings.llm.base_url or "https://api.openai.com/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.settings.llm.api_key}",
                "Content-Type": "application/json",
            }

            payload = {
                "model": "gpt-4o",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{mime_type};base64,{image_data}",
                                },
                            },
                        ],
                    }
                ],
                "max_tokens": 1500,
            }

            response = await self.client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            result = response.json()
            return result["choices"][0]["message"].get("content", "")
        else:
            # Local VLM fallback
            return await self._describe_with_local_vlm(image_path)

    async def _ocr_fallback(self, image_path: str) -> str:
        """Fallback to OCR when VLM is unavailable."""
        try:
            import pytesseract
            from PIL import Image

            image = Image.open(image_path)
            text = pytesseract.image_to_string(image, lang="chi_sim+eng")
            return f"OCR提取的文字: {text[:500]}"
        except ImportError:
            return "无法处理此图片（VLM和OCR均不可用）"
        except Exception as e:
            return f"图片处理失败: {str(e)}"

    def _extract_json_from_response(self, text: str) -> dict[str, Any]:
        """Extract JSON from LLM response."""
        try:
            if "```json" in text:
                json_str = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                json_str = text.split("```")[1].split("```")[0]
            else:
                # Try to find JSON object
                start = text.find("{")
                end = text.rfind("}")
                if start >= 0 and end > start:
                    json_str = text[start:end + 1]
                else:
                    return {"raw": text}

            return json.loads(json_str.strip())
        except (json.JSONDecodeError, IndexError):
            return {"raw": text}

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
