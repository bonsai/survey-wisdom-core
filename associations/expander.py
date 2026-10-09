"""
クエリ拡張・ワード連想エンジン。
静的辞書 + LLM動的生成のハイブリッド。
"""

import json
from pathlib import Path
from typing import Optional
from pydantic import BaseModel

ASSOC_DIR = Path(__file__).parent
DICT_PATH = ASSOC_DIR / "synonym_dict.json"


class ExpansionResult(BaseModel):
    original: str
    synonyms: list[str]          # 同義語・別表現
    hypernyms: list[str]        # 上位概念
    hyponyms: list[str]        # 下位概念
    adjacents: list[str]        # 隣接領域（関連だが別カテゴリ）
    impl_terms: list[str]       # 実装上よく使われる言い換え
    
    def all_terms(self) -> list[str]:
        seen = set()
        out = []
        for t in self.synonyms + self.hypernyms + self.hyponyms + self.adjacents + self.impl_terms:
            low = t.lower()
            if low not in seen:
                seen.add(low)
                out.append(t)
        return out


class QueryExpander:
    """
    入力ワード/フレーズから、サーベイクエリ候補を複数生成。
    まず静的辞書を参照し、なければ LLM フォールバック。
    """

    def __init__(self, llm_fn: Optional[callable] = None):
        self._dict: dict[str, dict] = self._load_dict()
        self._llm = llm_fn  # 任意: (prompt:str) -> str

    def expand(self, query: str, domain: str = "auto") -> ExpansionResult:
        # 1. 静的辞書ヒット
        if query.lower() in self._dict:
            d = self._dict[query.lower()]
            return ExpansionResult(original=query, **d)

        # 2. 部分マッチ
        for k, v in self._dict.items():
            if k in query.lower() or query.lower() in k:
                return ExpansionResult(original=query, **v)

        # 3. LLM 動的生成（利用可能な場合）
        if self._llm:
            return self._expand_by_llm(query, domain)

        # 4. 最低限の単語分割ベース
        return self._expand_by_token(query)

    def generate_search_queries(
        self, query: str, domain: str = "auto", max_terms: int = 8
    ) -> list[str]:
        """
        サーベイ用の実際の検索クエリ文字列を生成。
        e.g. "workflow engine" → [
            "workflow engine",
            "orchestrator framework",
            "DAG executor python",
            "state machine library",
        ]
        """
        ex = self.expand(query, domain)
        terms = ex.all_terms()[:max_terms]
        
        # オリジナル + 各連想語
        searches = [query]
        for t in terms:
            if domain == "repo":
                searches.append(f"{t} github")
            elif domain == "paper":
                searches.append(f"{t}")
            else:
                searches.append(t)
        
        # 重複除去（大文字小文字無視）
        seen: set[str] = set()
        out: list[str] = []
        for s in searches:
            low = s.lower()
            if low not in seen:
                seen.add(low)
                out.append(s)
        return out

    # ─── internals ─────────────────────────────────────────

    def _load_dict(self) -> dict[str, dict]:
        if DICT_PATH.exists():
            with open(DICT_PATH, encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _expand_by_llm(self, query: str, domain: str) -> ExpansionResult:
        prompt = f"""以下のテーマに関して、サーベイ調査に役立つ関連語を出力してください。
テーマ: {query}
領域: {domain}

JSON形式で出力:
{{
  "synonyms": ["...", "..."],
  "hypernyms": ["..."],
  "hyponyms": ["..."],
  "adjacents": ["..."],
  "impl_terms": ["..."]
}}
"""
        raw = self._llm(prompt)  # type: ignore
        try:
            d = json.loads(raw.strip().strip("`").replace("json", "").strip())
            return ExpansionResult(original=query, **d)
        except Exception:
            return ExpansionResult(original=query, synonyms=[], hypernyms=[], hyponyms=[], adjacents=[], impl_terms=[])

    def _expand_by_token(self, query: str) -> ExpansionResult:
        # 最も簡易: 空白区切りの各単語を逆順でも試す
        tokens = query.lower().split()
        variants = [query, " ".join(reversed(tokens)), " ".join(tokens[:2])]
        return ExpansionResult(
            original=query,
            synonyms=list(dict.fromkeys(variants)),
            hypernyms=[],
            hyponyms=[],
            adjacents=[],
            impl_terms=[],
        )
