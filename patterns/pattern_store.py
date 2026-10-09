"""
過去のサーベイから「知恵の型」を蓄積・検索。
ケースベース推論 + 教訓の抽出・転用。
"""

import json
import math
from pathlib import Path
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field

STORE_DIR = Path(__file__).parent
STORE_PATH = STORE_DIR / "survey_patterns.jsonl"


class LessonLearned(BaseModel):
    """1個の教訓・洞察。"""
    what: str                           # 何が起きたか
    why: Optional[str] = None           # なぜ起きたか
    fix: Optional[str] = None           # どう対処したか
    applies_to: list[str] = []          # 適用可能なクエリパターン（キーワード）


class PatternRecord(BaseModel):
    """
    1回のサーベイ実行から抽出された「型」。
    成功/失敗に関わらず蓄積する。
    """
    id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    query: str                          # 元の調査質問
    domain: str                         # "paper" | "repo"
    
    # 採用された戦略
    chosen_approach: str                # e.g. "aggregated_gate_with_critic"
    effective_queries: list[str] = []   # 実際にヒットした検索クエリ
    discarded_queries: list[str] = []   # 無駄だったクエリ
    
    # 重み（チューニング結果）
    final_weights: Optional[dict[str, float]] = None
    
    # 結果メトリクス
    items_collected: int = 0
    items_passed_gate: int = 0
    iterations: int = 1                 # Micro-1→Macro→Micro-2 の往復
    
    # 教訓
    lessons: list[LessonLearned] = []
    
    # タグ
    tags: list[str] = []               # e.g. ["low_citation_domain", "fragmented_ecosystem"]


class PatternStore:
    """
    JSONL への追記・類似ケース検索。
    ベクトルDB不要: keyword overlap + domain match で十分な精度。
    """

    def __init__(self, path: Path = STORE_PATH):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    # ─── Write ─────────────────────────────────────────────

    def append(self, record: PatternRecord) -> None:
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(record.model_dump_json() + "\n")

    # ─── Read ──────────────────────────────────────────────

    def load_all(self) -> list[PatternRecord]:
        if not self.path.exists():
            return []
        records = []
        with open(self.path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    records.append(PatternRecord(**d))
                except Exception:
                    continue
        return records

    # ─── Retrieve ──────────────────────────────────────────

    def find_similar(
        self,
        query: str,
        domain: Optional[str] = None,
        top_k: int = 5,
        min_score: float = 0.2,
    ) -> list[tuple[PatternRecord, float]]:
        """
        query と pattern の keyword overlap で類似度を計算。
        domain が指定されていれば同ドメイン優先。
        """
        candidates = self.load_all()
        query_tokens = set(self._tokenize(query))
        
        scored: list[tuple[PatternRecord, float]] = []
        for rec in candidates:
            if domain and rec.domain != domain:
                continue
            
            rec_tokens = set(self._tokenize(rec.query))
            # Jaccard-like overlap
            if not rec_tokens:
                continue
            overlap = len(query_tokens & rec_tokens) / len(query_tokens | rec_tokens)
            
            # tags, applies_to も考慮
            extra_tokens = set()
            for t in rec.tags:
                extra_tokens.update(self._tokenize(t))
            for l in rec.lessons:
                extra_tokens.update(self._tokenize(l.what))
                extra_tokens.update(self._tokenize(" ".join(l.applies_to)))
            
            if extra_tokens:
                extra_overlap = len(query_tokens & extra_tokens) / len(query_tokens | extra_tokens)
                overlap = max(overlap, extra_overlap * 0.8)  # タグ一致は少し弱くカウント
            
            if overlap >= min_score:
                scored.append((rec, round(overlap, 3)))
        
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    def suggest_weights(self, query: str, domain: str) -> dict[str, float]:
        """
        類似ケースの平均重みを返す。ない場合はデフォルト。
        """
        similar = self.find_similar(query, domain=domain, top_k=3)
        if not similar:
            return {"relevance": 0.45, "quality": 0.25, "freshness": 0.15, "confidence": 0.15}
        
        totals: dict[str, float] = {}
        count = 0
        for rec, _ in similar:
            if rec.final_weights:
                for k, v in rec.final_weights.items():
                    totals[k] = totals.get(k, 0.0) + v
                count += 1
        
        if count == 0:
            return {"relevance": 0.45, "quality": 0.25, "freshness": 0.15, "confidence": 0.15}
        
        return {k: round(v / count, 3) for k, v in totals.items()}

    def warn_pitfalls(self, query: str, domain: str) -> list[str]:
        """類似ケースから落とし穴を予告。"""
        similar = self.find_similar(query, domain=domain, top_k=5)
        warnings: list[str] = []
        seen: set[str] = set()
        for rec, score in similar:
            for l in rec.lessons:
                if l.why and l.why not in seen:
                    warnings.append(f"[{rec.query[:30]}...] {l.why}")
                    seen.add(l.why)
        return warnings

    # ─── internals ─────────────────────────────────────────

    def _tokenize(self, text: str) -> list[str]:
        import re
        return [t.lower() for t in re.findall(r"[a-zA-Z\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FAF]+", text) if len(t) > 1]
