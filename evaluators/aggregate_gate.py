"""集約スコアリング型評価ゲート — paper/repo 両対応."""

import math
from typing import Callable, Generic, TypeVar, Optional
from pydantic import BaseModel, Field

from ..schemes.models import (
    PaperMicro1, RepoMicro1, Evidence,
    MacroLandscape, CoverageCell,
)

T = TypeVar("T", PaperMicro1, RepoMicro1)


class ScoreResult(BaseModel):
    key: str
    relevance: float = Field(..., ge=0.0, le=1.0)
    quality: float = Field(..., ge=0.0, le=1.0)
    freshness: float = Field(..., ge=0.0, le=1.0)
    confidence: float = Field(..., ge=0.0, le=1.0)
    final: float = 0.0
    drop_reason: Optional[str] = None


class AggregateGate(Generic[T]):
    """
    収集 → スコアリング → 選別 → Macro 構造化 → Micro-2 再検証指示
    """

    def __init__(
        self,
        *,
        top_k: int = 15,
        min_relevance: float = 0.35,
        weights: dict[str, float] | None = None,
        domain: str = "paper",
    ):
        self.top_k = top_k
        self.min_relevance = min_relevance
        self.weights = weights or {
            "relevance": 0.45,
            "quality": 0.25,
            "freshness": 0.15,
            "confidence": 0.15,
        }
        self.domain = domain

    # ─── 1. Score ──────────────────────────────────────────

    def score(
        self,
        items: list[T],
        relevance_fn: Callable[[T], float],
        quality_fn: Optional[Callable[[T], float]] = None,
        freshness_fn: Optional[Callable[[T], float]] = None,
        confidence_fn: Optional[Callable[[T], float]] = None,
    ) -> list[ScoreResult]:
        """すべてのアイテムに4軸スコアを付与。"""
        results: list[ScoreResult] = []
        for it in items:
            key = it.title if hasattr(it, "title") else it.full_name  # type: ignore

            rel = relevance_fn(it)
            qual = quality_fn(it) if quality_fn else self._default_quality(it)
            fresh = freshness_fn(it) if freshness_fn else self._default_freshness(it)
            conf = confidence_fn(it) if confidence_fn else self._default_confidence(it)

            final = (
                rel * self.weights["relevance"]
                + qual * self.weights["quality"]
                + fresh * self.weights["freshness"]
                + conf * self.weights["confidence"]
            )

            results.append(
                ScoreResult(
                    key=key,
                    relevance=rel,
                    quality=qual,
                    freshness=fresh,
                    confidence=conf,
                    final=final,
                )
            )
        return results

    # ─── 2. Gate ───────────────────────────────────────────

    def gate(self, scored: list[ScoreResult]) -> list[ScoreResult]:
        """閾値通過 + TOP_K 選別。"""
        passed: list[ScoreResult] = []
        for s in scored:
            if s.relevance < self.min_relevance:
                s.drop_reason = f"relevance {s.relevance:.2f} < {self.min_relevance}"
                continue
            passed.append(s)

        passed.sort(key=lambda x: x.final, reverse=True)
        for s in passed[self.top_k :]:
            s.drop_reason = f"ranked_out_of_top_{self.top_k}"
        return [s for s in passed[: self.top_k] if not s.drop_reason]

    # ─── 3. Macro Matrix Builder ───────────────────────────

    def build_macro(
        self,
        items: list[T],
        col_keys: list[str],
        fill_fn: Callable[[T, str], Optional[float]],
    ) -> MacroLandscape:
        """
        Micro-1 items × col_keys で Coverage Matrix を構築。
        col_keys は e.g. ['精度', '速度', 'スケーラビリティ', '解釈性'] (paper)
        または ['Web UI', 'API', '拡張性', 'ドキュメント'] (repo)
        """
        cells: list[CoverageCell] = []
        outlier_keys: list[str] = []

        for it in items:
            key = it.title if hasattr(it, "title") else it.full_name  # type: ignore
            has_any = False
            for col in col_keys:
                score = fill_fn(it, col)
                cell = CoverageCell(row_key=key, col_key=col, filled=score is not None)
                if score is not None:
                    cell.score = score
                    has_any = True
                cells.append(cell)
            if not has_any:
                outlier_keys.append(key)

        # 単純クラスタリング: 同じ filled パターンを持つものをグループ化
        pattern_map: dict[str, list[str]] = {}
        for it in items:
            key = it.title if hasattr(it, "title") else it.full_name  # type: ignore
            pattern = tuple(
                c.filled and c.score is not None and c.score > 0.5
                for c in cells
                if c.row_key == key
            )
            pattern_map.setdefault(str(pattern), []).append(key)
        clusters = [v for v in pattern_map.values() if len(v) > 1]

        # Gap: どの列も埋まっていない領域（ここでは「全アイテムで score率低い列」）
        col_coverage = {col: 0.0 for col in col_keys}
        for col in col_keys:
            vals = [c.score for c in cells if c.col_key == col and c.score is not None]
            if vals:
                col_coverage[col] = sum(vals) / len(vals)
        gap_regions = [c for c, v in col_coverage.items() if v < 0.3]

        return MacroLandscape(
            domain="paper" if self.domain == "paper" else "repo",  # type: ignore
            coverage_matrix=cells,
            clusters=clusters,
            gap_regions=gap_regions,
            outlier_keys=outlier_keys,
        )

    # ─── Defaults ──────────────────────────────────────────

    def _default_quality(self, it: T) -> float:
        if isinstance(it, PaperMicro1):
            # citation の対数スコア + claims の数
            cit = it.citation_count or 0
            return min(1.0, (math.log10(cit + 1) / 4) + (len(it.claims) * 0.05))
        else:  # RepoMicro1
            # stars + forks の信号（生数値ではなく飽和）
            signal = math.log10((it.stars or 0) + (it.forks or 0) + 1)
            return min(1.0, signal / 5)

    def _default_freshness(self, it: T) -> float:
        from datetime import datetime
        if isinstance(it, PaperMicro1):
            yr = it.year or 2010
            return min(1.0, max(0.0, (yr - 2010) / 15))
        else:
            updated = it.updated_at
            if updated:
                days = (datetime.utcnow() - updated).days
                return max(0.0, 1.0 - (days / 730))  # 2年で0
            return 0.5

    def _default_confidence(self, it: T) -> float:
        if isinstance(it, PaperMicro1):
            return 1.0 if it.semantic_scholar_id else 0.6
        else:
            return 1.0 if it.license else 0.5
