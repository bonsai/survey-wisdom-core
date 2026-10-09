"""Pydantic models for the 3-layer survey structure."""

from typing import Literal, Optional
from pydantic import BaseModel, Field
from datetime import datetime

# ─── Evidence Types ──────────────────────────────────────────

class Evidence(BaseModel):
    """単一のエビデンス断片。"""
    text: str
    type: Literal["Fact", "Assessment", "Hypothesis"] = "Assessment"
    source_url: Optional[str] = None
    source_ref: Optional[str] = None  # e.g. "論文 3章" or "README line 45"
    confidence: Literal["high", "medium", "low"] = "medium"

# ─── MICRO-1: Individual Element ────────────────────────────

class PaperMicro1(BaseModel):
    """論文1本の原子的事実。"""
    title: str
    authors: list[str] = []
    year: Optional[int] = None
    venue: Optional[str] = None
    abstract: Optional[str] = None
    keywords: list[str] = []
    semantic_scholar_id: Optional[str] = None
    citation_count: Optional[int] = None
    # 抽出セクション
    claims: list[Evidence] = []          # 主張→エビデンス対
    methodology: list[Evidence] = []
    limitations: list[Evidence] = []
    evaluation_metrics: list[str] = []

class RepoMicro1(BaseModel):
    """リポジトリ1つの原子的事実。"""
    full_name: str
    description: Optional[str] = None
    url: Optional[str] = None
    language: Optional[str] = None
    license: Optional[str] = None
    stars: int = 0
    forks: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    topics: list[str] = []
    # 抽出サーフェス
    capabilities: list[Evidence] = []    # 謳い文句→実装確認
    api_surface: list[str] = []
    dependencies: list[str] = []
    test_evidence: Optional[str] = None

# ─── MACRO: Structure / Pattern ─────────────────────────────

class CoverageCell(BaseModel):
    """マトリクスの1セル。パターン化された比較単位。"""
    row_key: str        # e.g. 手法名 / リポジトリ名
    col_key: str        # e.g. 評価軸 / 課題カテゴリ
    filled: bool = False
    evidence: list[Evidence] = []
    score: Optional[float] = None  # 0.0-1.0

class MacroLandscape(BaseModel):
    """全体マップ。"""
    domain: Literal["paper", "repo"]
    coverage_matrix: list[CoverageCell] = []
    clusters: list[list[str]] = []      # グループ化された row_key のリスト
    gap_regions: list[str] = []          # 未踏空間の識別子
    outlier_keys: list[str] = []         # 異常値（孤立点）
    timeline_events: list[tuple[int, str]] = []  # (year, event)

# ─── MICRO-2: Verification ───────────────────────────────────

class VerificationTask(BaseModel):
    """Macroで見えたパターンを元に出された再検証タスク。"""
    trigger: str                         # なぜ再検証が必要か
    target_keys: list[str]              # 再検査対象の row_key
    operation: Literal[
        "claim_verification",
        "evidence_chain_audit",
        "contradiction_resolution",
        "api_surface_audit",
        "test_evidence_check",
        "integration_dry_run",
    ]
    status: Literal["pending", "done", "failed"] = "pending"
    result: Optional[str] = None

# ─── Unified Container ──────────────────────────────────────

class SurveyUniverse(BaseModel):
    """
    1回のサーベイ実行全体のコンテナ。
    Micro-1 → Macro → Micro-2 の循環を保持。
    """
    query: str                           # 元の調査質問
    domain: Literal["paper", "repo"]
    
    # Layer 1
    micro1_items: list[PaperMicro1 | RepoMicro1] = []
    
    # Layer 2
    macro: Optional[MacroLandscape] = None
    
    # Layer 3
    micro2_tasks: list[VerificationTask] = []
    
    # メタ
    created_at: datetime = Field(default_factory=datetime.utcnow)
    iteration: int = 1                   # Micro-1→Macro→Micro-2 の往復回数
