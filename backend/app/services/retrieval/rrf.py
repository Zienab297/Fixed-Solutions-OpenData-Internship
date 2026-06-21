"""
Reciprocal Rank Fusion (RRF) — merges multiple ranked lists.

Improvements over original:
- Accepts per-list weights so signals are not treated as equal.
  Vector (bge-m3 cosine) is generally more reliable than BM25 tsvector,
  so callers can pass weights=[1.0, 0.7] to reflect that.
- Preserves the original vector similarity score (before RRF) on each item
  so _calculate_confidence() in the pipeline has a meaningful number to work with.
- Validates weight list length matches results_lists length.
"""

from typing import List, Optional
from collections import defaultdict


def reciprocal_rank_fusion(
    results_lists: List[List[dict]],
    top_k: int = 10,
    k: int = 60,
    weights: Optional[List[float]] = None,
) -> List[dict]:
    """
    Weighted RRF across multiple ranked result lists.

    score(item) = sum over lists:  weight_i / (k + rank_i)

    Args:
        results_lists:  Each inner list is a ranked list of chunk dicts.
                        Items must have an "id" key.
        top_k:          Number of results to return.
        k:              RRF constant. 60 is the standard empirical default.
        weights:        Per-list multipliers. Defaults to 1.0 for all lists.
                        Example: [1.0, 0.7] means vector outweighs BM25.

    Returns:
        Fused list sorted by rrf_score descending, each item augmented with:
        - rrf_score:        the weighted RRF score used for ranking
        - score:            alias for rrf_score (pipeline compatibility)
        - original_score:   the score the item had in its best-ranked source list
    """
    if not results_lists:
        return []

    if weights is None:
        weights = [1.0] * len(results_lists)

    if len(weights) != len(results_lists):
        raise ValueError(
            f"weights length ({len(weights)}) must match "
            f"results_lists length ({len(results_lists)})"
        )

    rrf_scores: dict[str, float] = defaultdict(float)
    original_scores: dict[str, float] = {}
    items: dict[str, dict] = {}

    for results, weight in zip(results_lists, weights):
        for rank, item in enumerate(results, start=1):
            item_id = item.get("id")
            if not item_id:
                continue

            rrf_scores[item_id] += weight / (k + rank)

            # Keep the highest original score seen across lists for this item
            raw_score = float(item.get("score", 0.0))
            if item_id not in original_scores or raw_score > original_scores[item_id]:
                original_scores[item_id] = raw_score
                items[item_id] = item   # store the version with the best raw score

    sorted_ids = sorted(rrf_scores, key=lambda x: rrf_scores[x], reverse=True)

    fused = []
    for item_id in sorted_ids[:top_k]:
        item = items[item_id].copy()
        item["rrf_score"]      = rrf_scores[item_id]
        item["score"]          = rrf_scores[item_id]
        item["original_score"] = original_scores[item_id]
        fused.append(item)

    return fused