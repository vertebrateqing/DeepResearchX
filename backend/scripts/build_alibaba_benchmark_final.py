"""Build final RAG benchmark dataset from Alibaba FY2025 annual report.

This script uses manually verified chunk IDs based on real text search
instead of relying on FakeEmbedding retrieval (which has poor semantic quality).

Usage:
    cd backend
    uv run python scripts/build_alibaba_benchmark_final.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


def main() -> int:
    collection_name = "alibaba_fy2025_benchmark"
    doc_id = "f3ab57593d974f06933030f3ef62aae3"

    # All chunk IDs are manually verified by text-searching the inspection file.
    # Each relevant_chunk_ids list contains chunks that directly answer the query.
    # relevance_scores: 2 = directly answers, 1 = partially relevant, 0 = irrelevant

    benchmark_cases = [
        # ------------------------------------------------------------------
        # 1. 精确事实查询 — 总收入
        # ------------------------------------------------------------------
        {
            "query_id": "alibaba_001",
            "query": "阿里巴巴2025財年的總收入是多少",
            "collection_name": collection_name,
            "relevant_doc_ids": [doc_id],
            "relevant_chunk_ids": [
                "f3ab57593d974f06933030f3ef62aae3__chunk__225",
                "f3ab57593d974f06933030f3ef62aae3__chunk__171",
                "f3ab57593d974f06933030f3ef62aae3__chunk__195",
            ],
            "relevance_scores": {
                "f3ab57593d974f06933030f3ef62aae3__chunk__225": 2,  # "總收入從2024財年的人民幣941,168百萬元增長6%至2025財年的人民幣996,347百萬元"
                "f3ab57593d974f06933030f3ef62aae3__chunk__171": 2,  # 財務概要表格: 收入 996,347
                "f3ab57593d974f06933030f3ef62aae3__chunk__195": 2,  # 分部收入表格: 合併收入 996,347
            },
            "category": "exact_fact",
            "query_type": "精确事实查询",
            "expected_answer": "人民幣996,347百萬元（約137,300百萬美元），較2024財年增長6%",
        },

        # ------------------------------------------------------------------
        # 2. 精确事实查询 — 淘天集团客户管理收入
        # ------------------------------------------------------------------
        {
            "query_id": "alibaba_002",
            "query": "淘天集團2025財年的客戶管理收入是多少",
            "collection_name": collection_name,
            "relevant_doc_ids": [doc_id],
            "relevant_chunk_ids": [
                "f3ab57593d974f06933030f3ef62aae3__chunk__194",
                "f3ab57593d974f06933030f3ef62aae3__chunk__227",
            ],
            "relevance_scores": {
                "f3ab57593d974f06933030f3ef62aae3__chunk__194": 2,  # 分部收入表格: 客戶管理 322,346
                "f3ab57593d974f06933030f3ef62aae3__chunk__227": 2,  # "客戶管理收入同比增長6%"
            },
            "category": "exact_fact",
            "query_type": "精确事实查询",
            "expected_answer": "人民幣322,346百萬元（44,420百萬美元），同比增長6%",
        },

        # ------------------------------------------------------------------
        # 3. 多条件查询 — 云智能集团收入+市场地位
        # ------------------------------------------------------------------
        {
            "query_id": "alibaba_003",
            "query": "雲智能集團2025財年的收入及全球市場排名",
            "collection_name": collection_name,
            "relevant_doc_ids": [doc_id],
            "relevant_chunk_ids": [
                "f3ab57593d974f06933030f3ef62aae3__chunk__194",
                "f3ab57593d974f06933030f3ef62aae3__chunk__13",
                "f3ab57593d974f06933030f3ef62aae3__chunk__37",
            ],
            "relevance_scores": {
                "f3ab57593d974f06933030f3ef62aae3__chunk__194": 2,  # 分部收入表格: 雲智能集團 118,028
                "f3ab57593d974f06933030f3ef62aae3__chunk__13": 2,  # "世界第四大、亞太地區最大的基礎設施即服務提供者"
                "f3ab57593d974f06933030f3ef62aae3__chunk__37": 2,  # 同上，另一处
            },
            "category": "multi_condition",
            "query_type": "多条件查询",
            "expected_answer": "2025財年收入人民幣118,028百萬元（16,265百萬美元）；世界第四大、亞太地區最大的IaaS提供商，中國最大的公共雲服務提供商",
        },

        # ------------------------------------------------------------------
        # 4. 精确事实查询 — 阿里国际数字商业集团收入
        # ------------------------------------------------------------------
        {
            "query_id": "alibaba_004",
            "query": "阿里國際數字商業集團2025財年的總收入是多少",
            "collection_name": collection_name,
            "relevant_doc_ids": [doc_id],
            "relevant_chunk_ids": [
                "f3ab57593d974f06933030f3ef62aae3__chunk__194",
                "f3ab57593d974f06933030f3ef62aae3__chunk__34",
            ],
            "relevance_scores": {
                "f3ab57593d974f06933030f3ef62aae3__chunk__194": 2,  # 分部收入表格: 合計 132,300
                "f3ab57593d974f06933030f3ef62aae3__chunk__34": 1,  # "國際零售商業業務共同實現33%的收入增長"
            },
            "category": "exact_fact",
            "query_type": "精确事实查询",
            "expected_answer": "人民幣132,300百萬元（18,231百萬美元），其中國際零售商業108,465百萬元，國際批發商業23,835百萬元",
        },

        # ------------------------------------------------------------------
        # 5. 语义近义查询 — AI基础设施投入（用词不同）
        # ------------------------------------------------------------------
        {
            "query_id": "alibaba_005",
            "query": "阿里巴巴在人工智能和雲計算硬件方面的資本投入策略",
            "collection_name": collection_name,
            "relevant_doc_ids": [doc_id],
            "relevant_chunk_ids": [
                "f3ab57593d974f06933030f3ef62aae3__chunk__4",
                "f3ab57593d974f06933030f3ef62aae3__chunk__5",
                "f3ab57593d974f06933030f3ef62aae3__chunk__7",
            ],
            "relevance_scores": {
                "f3ab57593d974f06933030f3ef62aae3__chunk__4": 2,  # "加大對雲和AI基礎設施的投入"
                "f3ab57593d974f06933030f3ef62aae3__chunk__5": 2,  # "全力投入AI基礎設施和技術先進性建設"
                "f3ab57593d974f06933030f3ef62aae3__chunk__7": 1,  # "加大對AI領域的戰略性投資"
            },
            "category": "semantic",
            "query_type": "语义近义查询",
            "expected_answer": "阿里巴巴聚焦以AI為核心的未來方向，加大對雲和AI基礎設施的投入，全力投入AI基礎設施和技術先進性建設",
        },

        # ------------------------------------------------------------------
        # 6. 长文档综合查询 — 股东回报策略（跨chunk整合）
        # ------------------------------------------------------------------
        {
            "query_id": "alibaba_006",
            "query": "阿里巴巴2025財年的股東回報策略包括哪些內容",
            "collection_name": collection_name,
            "relevant_doc_ids": [doc_id],
            "relevant_chunk_ids": [
                "f3ab57593d974f06933030f3ef62aae3__chunk__7",
                "f3ab57593d974f06933030f3ef62aae3__chunk__675",
            ],
            "relevance_scores": {
                "f3ab57593d974f06933030f3ef62aae3__chunk__7": 2,  # 股息46億美元+回購119億美元
                "f3ab57593d974f06933030f3ef62aae3__chunk__675": 2,  # 股份回購計劃詳情: 回購10.78億股，總對價107億美元
            },
            "category": "comprehensive",
            "query_type": "长文档综合查询",
            "expected_answer": "派發年度及特別股息共計46億美元；股份回購計劃下回購119億美元集團股份，總股本淨減少5.1%",
        },

        # ------------------------------------------------------------------
        # 7. 精确事实查询 — 净利润
        # ------------------------------------------------------------------
        {
            "query_id": "alibaba_007",
            "query": "阿里巴巴2025財年的淨利潤是多少",
            "collection_name": collection_name,
            "relevant_doc_ids": [doc_id],
            "relevant_chunk_ids": [
                "f3ab57593d974f06933030f3ef62aae3__chunk__171",
                "f3ab57593d974f06933030f3ef62aae3__chunk__966",
                "f3ab57593d974f06933030f3ef62aae3__chunk__207",
            ],
            "relevance_scores": {
                "f3ab57593d974f06933030f3ef62aae3__chunk__171": 2,  # 財務概要表格: 淨利潤 125,976
                "f3ab57593d974f06933030f3ef62aae3__chunk__966": 2,  # 財務報表: 淨利潤 125,976
                "f3ab57593d974f06933030f3ef62aae3__chunk__207": 2,  # 淨利潤 125,976
            },
            "category": "exact_fact",
            "query_type": "精确事实查询",
            "expected_answer": "人民幣125,976百萬元（17,360百萬美元）；歸屬於普通股股東的淨利潤為人民幣129,470百萬元",
        },

        # ------------------------------------------------------------------
        # 8. 多条件查询 — 国际零售业务增长+具体平台表现
        # ------------------------------------------------------------------
        {
            "query_id": "alibaba_008",
            "query": "阿里國際數字商業集團旗下各平台在2025財年的表現如何",
            "collection_name": collection_name,
            "relevant_doc_ids": [doc_id],
            "relevant_chunk_ids": [
                "f3ab57593d974f06933030f3ef62aae3__chunk__34",
                "f3ab57593d974f06933030f3ef62aae3__chunk__11",
                "f3ab57593d974f06933030f3ef62aae3__chunk__12",
                "f3ab57593d974f06933030f3ef62aae3__chunk__5",
            ],
            "relevance_scores": {
                "f3ab57593d974f06933030f3ef62aae3__chunk__34": 2,  # "國際零售商業業務共同實現33%的收入增長"
                "f3ab57593d974f06933030f3ef62aae3__chunk__11": 2,  # 速賣通、Trendyol、Lazada介紹
                "f3ab57593d974f06933030f3ef62aae3__chunk__12": 2,  # Lazada東南亞領先電商平台
                "f3ab57593d974f06933030f3ef62aae3__chunk__5": 1,  # "海外電商方面...整體收入保持強勁增長"
            },
            "category": "multi_condition",
            "query_type": "多条件查询",
            "expected_answer": "國際零售商業業務共同實現33%的收入增長；速賣通覆蓋超過200個國家和地區；Trendyol和Lazada分別在土耳其和東南亞市場表現強勁",
        },

        # ------------------------------------------------------------------
        # 9. 长文档综合查询 — 竞争风险（跨多个chunk）
        # ------------------------------------------------------------------
        {
            "query_id": "alibaba_009",
            "query": "阿里巴巴2025財年面臨的主要競爭和監管風險有哪些",
            "collection_name": collection_name,
            "relevant_doc_ids": [doc_id],
            "relevant_chunk_ids": [
                "f3ab57593d974f06933030f3ef62aae3__chunk__61",
                "f3ab57593d974f06933030f3ef62aae3__chunk__315",
                "f3ab57593d974f06933030f3ef62aae3__chunk__422",
            ],
            "relevance_scores": {
                "f3ab57593d974f06933030f3ef62aae3__chunk__61": 2,   # 競爭風險詳細描述
                "f3ab57593d974f06933030f3ef62aae3__chunk__315": 2,  # VIE結構監管風險
                "f3ab57593d974f06933030f3ef62aae3__chunk__422": 1,  # 支付寶/螞蟻集團監管風險
            },
            "category": "comprehensive",
            "query_type": "长文档综合查询",
            "expected_answer": "競爭風險（電商、雲計算、人才競爭）；監管風險（中國法律法規變化、VIE結構不確定性、反壟斷、數據安全）",
        },

        # ------------------------------------------------------------------
        # 10. 负例/无关查询 — 文档中不存在的信息
        # ------------------------------------------------------------------
        {
            "query_id": "alibaba_010",
            "query": "蘋果公司2025財年的iPhone銷售收入是多少",
            "collection_name": collection_name,
            "relevant_doc_ids": [],
            "relevant_chunk_ids": [],
            "relevance_scores": {},
            "category": "negative",
            "query_type": "负例/无关查询",
            "expected_answer": "文檔中未包含蘋果公司或iPhone相關信息",
        },
    ]

    # Write benchmark
    benchmark_path = Path("deep_research/evaluation/datasets/alibaba_fy2025_benchmark.jsonl")
    benchmark_path.parent.mkdir(parents=True, exist_ok=True)

    with open(benchmark_path, "w", encoding="utf-8") as f:
        for case in benchmark_cases:
            f.write(json.dumps(case, ensure_ascii=False) + "\n")

    print(f"Benchmark saved to: {benchmark_path}")
    print(f"Total queries: {len(benchmark_cases)}")

    # Print summary
    from collections import Counter
    cats = Counter(c["category"] for c in benchmark_cases)
    print("\nCategory distribution:")
    for cat, count in cats.most_common():
        print(f"  {cat}: {count}")

    # Verify all referenced chunk IDs exist
    print("\nVerifying chunk IDs...")
    inspect_path = Path("/tmp/alibaba_benchmark/chunks_inspection.json")
    if inspect_path.exists():
        with open(inspect_path, "r", encoding="utf-8") as f:
            all_chunks = json.load(f)
        all_ids = {c["id"] for c in all_chunks}

        missing = []
        for case in benchmark_cases:
            for cid in case["relevant_chunk_ids"]:
                if cid not in all_ids:
                    missing.append((case["query_id"], cid))

        if missing:
            print(f"  WARNING: {len(missing)} referenced chunk IDs not found:")
            for qid, cid in missing:
                print(f"    {qid}: {cid}")
        else:
            print("  All referenced chunk IDs verified ✓")

    return 0


if __name__ == "__main__":
    sys.exit(main())
