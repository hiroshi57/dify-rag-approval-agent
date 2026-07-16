import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from rag_agent import RegulationRegistry, check_answer_staleness  # noqa: E402


def _registry():
    r = RegulationRegistry()
    r.register("経費精算規程", "v1", {"第3条": "締め日は毎月20日", "第4条": "上長承認"})
    r.register("経費精算規程", "v2", {"第3条": "締め日は毎月25日", "第4条": "上長承認",
                                     "第5条": "証憑必須"})
    return r


def test_diff_detects_changes():
    d = _registry().diff("経費精算規程", "v1", "v2")
    assert d.changed == ["第3条"]       # 締め日変更
    assert d.added == ["第5条"]
    assert d.removed == []


def test_stale_when_cited_changed_section():
    r = _registry()
    # v1 の第3条を引用 -> v2で改定済み -> 陳腐化
    assert r.is_stale("経費精算規程", "第3条", "v1") is True
    # v1 の第4条は不変 -> 陳腐化なし
    assert r.is_stale("経費精算規程", "第4条", "v1") is False
    # 最新版の引用は陳腐化なし
    assert r.is_stale("経費精算規程", "第3条", "v2") is False


def test_unknown_version_is_stale():
    assert _registry().is_stale("経費精算規程", "第3条", "v0") is True


def test_check_answer_staleness_lists_stale():
    r = _registry()
    stale = check_answer_staleness(r, [
        {"doc_id": "経費精算規程", "section_id": "第3条", "version": "v1"},
        {"doc_id": "経費精算規程", "section_id": "第4条", "version": "v1"},
    ])
    assert len(stale) == 1
    assert stale[0].section_id == "第3条"
    assert stale[0].latest_version == "v2"


def test_diff_missing_version_raises():
    with pytest.raises(KeyError):
        _registry().diff("経費精算規程", "v1", "v9")
