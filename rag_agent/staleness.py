"""規程改定の差分追跡 + 回答の陳腐化検知(尖った武器).

規程はバージョン管理され改定される。過去の回答が「古い版の条項」を引用していないかを
検知し、改定された条項に基づく回答は再確認を促す(コンプラRAGの決定的差別化)。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class RegulationVersion:
    version: str
    sections: Dict[str, str]     # section_id -> text


@dataclass
class VersionDiff:
    added: List[str]
    removed: List[str]
    changed: List[str]

    def as_dict(self):
        return {"added": self.added, "removed": self.removed, "changed": self.changed}


class RegulationRegistry:
    """規程のバージョン履歴を保持し、差分と陳腐化を判定する."""

    def __init__(self) -> None:
        # doc_id -> [RegulationVersion...] (登録順)
        self._history: Dict[str, List[RegulationVersion]] = {}

    def register(self, doc_id: str, version: str, sections: Dict[str, str]) -> None:
        self._history.setdefault(doc_id, []).append(RegulationVersion(version, dict(sections)))

    def latest(self, doc_id: str) -> Optional[RegulationVersion]:
        vs = self._history.get(doc_id)
        return vs[-1] if vs else None

    def diff(self, doc_id: str, old_version: str, new_version: str) -> VersionDiff:
        vs = {v.version: v for v in self._history.get(doc_id, [])}
        if old_version not in vs or new_version not in vs:
            raise KeyError("指定バージョンが存在しません")
        old, new = vs[old_version].sections, vs[new_version].sections
        added = [s for s in new if s not in old]
        removed = [s for s in old if s not in new]
        changed = [s for s in new if s in old and new[s] != old[s]]
        return VersionDiff(sorted(added), sorted(removed), sorted(changed))

    def is_stale(self, doc_id: str, section_id: str, cited_version: str) -> bool:
        """引用した版以降にその条項が改定/削除されていれば陳腐化."""
        vs = self._history.get(doc_id, [])
        versions = [v.version for v in vs]
        if cited_version not in versions:
            return True   # 未知の版=最新でない可能性
        idx = versions.index(cited_version)
        cited_text = vs[idx].sections.get(section_id)
        for later in vs[idx + 1:]:
            if section_id not in later.sections:      # 削除された
                return True
            if later.sections[section_id] != cited_text:  # 改定された
                return True
        return False


@dataclass
class StaleCitation:
    doc_id: str
    section_id: str
    cited_version: str
    latest_version: str


def check_answer_staleness(registry: RegulationRegistry,
                           citations: List[Dict]) -> List[StaleCitation]:
    """citations: [{doc_id, section_id, version}]. 陳腐化した引用の一覧を返す."""
    stale: List[StaleCitation] = []
    for c in citations:
        if registry.is_stale(c["doc_id"], c["section_id"], c["version"]):
            latest = registry.latest(c["doc_id"])
            stale.append(StaleCitation(c["doc_id"], c["section_id"], c["version"],
                                       latest.version if latest else "?"))
    return stale
