"""
Reciprocal Rank Fusion (RRF) — merges multiple ranked lists.
Simple, parameter-free, proven effective for hybrid retrieval.
"""
from typing import List
from collections import defaultdict


def reciprocal_rank_fusion(
    results_lists: List[List[dict]],
    top_k: int = 10,
    k: int = 60,  # RRF constant — 60 is standard default
) -> List[dict]:
    """
    Merge multiple ranked result lists using RRF.
    Score = sum(1 / (k + rank)) across all lists where the item appears.
    Higher score = more relevant across signals.
    """
    scores = defaultdict(float)
    items = {}

    for results in results_lists:
        for rank, item in enumerate(results, start=1):
            item_id = item.get("id")
            if item_id:
                scores[item_id] += 1.0 / (k + rank)
                items[item_id] = item

    # Sort by RRF score descending
    sorted_ids = sorted(scores, key=lambda x: scores[x], reverse=True)

    fused = []
    for item_id in sorted_ids[:top_k]:
        item = items[item_id].copy()
        item["rrf_score"] = scores[item_id]
        item["score"] = scores[item_id]
        fused.append(item)

    return fused
