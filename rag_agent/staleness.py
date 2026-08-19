"""規程改定の差分追跡 + 回答の陳腐化検知.

規程はバージョン管理され改定される。過去の回答が「古い版の条項」を引用していないかを
検知し、改定された条項に基づく回答は再確認を促す。

QAAgent に registry を渡すと、回答時に自動で引用の陳腐化を判定する
(旧実装ではこの機能がどこからも呼ばれておらず、実質デッドコードだった)。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional


@dataclass
class RegulationVersion:
    version: str
    sections: Dict[str, str]     # section_id -> text


@dataclass
class VersionDiff:
    added: List[str]
    removed: List[str]
    changed: List[str]

    @property
    def is_empty(self) -> bool:
        return not (self.added or self.removed or self.changed)

    def as_dict(self) -> Dict:
        return {"added": self.added, "removed": self.removed, "changed": self.changed}


class RegulationRegistry:
    """規程のバージョン履歴を保持し、差分と陳腐化を判定する.

    版の順序は **登録順** を正とする(セマンティックな大小比較はしない)。
    同じ版を二重登録すると履歴が壊れるため明示的に拒否する。
    """

    def __init__(self) -> None:
        self._history: Dict[str, List[RegulationVersion]] = {}

    def register(self, doc_id: str, version: str, sections: Dict[str, str]) -> None:
        if not version:
            raise ValueError("version は必須です")
        versions = self._history.setdefault(doc_id, [])
        if any(v.version == version for v in versions):
            raise ValueError(f"版が重複しています: {doc_id} {version}")
        versions.append(RegulationVersion(version, dict(sections)))

    def versions(self, doc_id: str) -> List[str]:
        return [v.version for v in self._history.get(doc_id, [])]

    def latest(self, doc_id: str) -> Optional[RegulationVersion]:
        vs = self._history.get(doc_id)
        return vs[-1] if vs else None

    def diff(self, doc_id: str, old_version: str, new_version: str) -> VersionDiff:
        if doc_id not in self._history:
            raise KeyError(f"未登録の規程です: {doc_id}")
        vs = {v.version: v for v in self._history[doc_id]}
        missing = [v for v in (old_version, new_version) if v not in vs]
        if missing:
            raise KeyError(f"指定バージョンが存在しません: {', '.join(missing)}")
        old, new = vs[old_version].sections, vs[new_version].sections
        added = [s for s in new if s not in old]
        removed = [s for s in old if s not in new]
        changed = [s for s in new if s in old and new[s] != old[s]]
        return VersionDiff(sorted(added), sorted(removed), sorted(changed))

    def is_stale(self, doc_id: str, section_id: str, cited_version: str) -> bool:
        """引用した版以降にその条項が改定/削除されていれば陳腐化(未知の版も陳腐化扱い)."""
        vs = self._history.get(doc_id, [])
        versions = [v.version for v in vs]
        if cited_version not in versions:
            return True
        idx = versions.index(cited_version)
        cited_text = vs[idx].sections.get(section_id)
        if cited_text is None:
            return True          # 引用元の版にその条項が無い = 引用自体が不正
        for later in vs[idx + 1:]:
            if section_id not in later.sections:
                return True
            if later.sections[section_id] != cited_text:
                return True
        return False


@dataclass
class StaleCitation:
    doc_id: str
    section_id: str
    cited_version: str
    latest_version: str

    def as_dict(self) -> Dict:
        return {"doc_id": self.doc_id, "section_id": self.section_id,
                "cited_version": self.cited_version, "latest_version": self.latest_version}


def _citation_fields(c) -> Dict:
    if isinstance(c, dict):
        return {"doc_id": c["doc_id"], "section_id": c["section_id"],
                "version": c.get("version", "")}
    return {"doc_id": c.doc_id, "section_id": c.section_id,
            "version": getattr(c, "version", "")}


def check_answer_staleness(registry: RegulationRegistry,
                           citations: Iterable) -> List[StaleCitation]:
    """citations: dict または Citation オブジェクトの列. 陳腐化した引用の一覧を返す."""
    stale: List[StaleCitation] = []
    for raw in citations:
        c = _citation_fields(raw)
        if registry.is_stale(c["doc_id"], c["section_id"], c["version"]):
            latest = registry.latest(c["doc_id"])
            stale.append(StaleCitation(c["doc_id"], c["section_id"], c["version"],
                                       latest.version if latest else "?"))
    return stale
