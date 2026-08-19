import pytest

from rag_agent import Citation, RegulationRegistry, check_answer_staleness


def _registry():
    r = RegulationRegistry()
    r.register("経費精算規程", "v1", {"第3条": "締め日は毎月20日", "第4条": "上長承認"})
    r.register("経費精算規程", "v2", {"第3条": "締め日は毎月25日", "第4条": "上長承認",
                                     "第5条": "証憑必須"})
    return r


def test_diff_detects_changes():
    d = _registry().diff("経費精算規程", "v1", "v2")
    assert d.changed == ["第3条"]
    assert d.added == ["第5条"]
    assert d.removed == []
    assert d.is_empty is False


def test_stale_when_cited_changed_section():
    r = _registry()
    assert r.is_stale("経費精算規程", "第3条", "v1") is True
    assert r.is_stale("経費精算規程", "第4条", "v1") is False
    assert r.is_stale("経費精算規程", "第3条", "v2") is False


def test_unknown_version_is_stale():
    assert _registry().is_stale("経費精算規程", "第3条", "v0") is True


def test_citation_of_nonexistent_section_is_stale():
    assert _registry().is_stale("経費精算規程", "第99条", "v1") is True


def test_removed_section_is_stale():
    r = RegulationRegistry()
    r.register("d", "v1", {"第1条": "a"})
    r.register("d", "v2", {})
    assert r.is_stale("d", "第1条", "v1") is True


def test_check_answer_staleness_accepts_dicts_and_citations():
    r = _registry()
    stale = check_answer_staleness(r, [
        {"doc_id": "経費精算規程", "section_id": "第3条", "version": "v1"},
        {"doc_id": "経費精算規程", "section_id": "第4条", "version": "v1"},
    ])
    assert len(stale) == 1 and stale[0].latest_version == "v2"

    stale2 = check_answer_staleness(r, [
        Citation(doc_id="経費精算規程", section_id="第3条", title="締め日", version="v1")])
    assert len(stale2) == 1


def test_duplicate_version_is_rejected():
    r = _registry()
    with pytest.raises(ValueError):
        r.register("経費精算規程", "v2", {})


def test_diff_missing_version_raises():
    with pytest.raises(KeyError):
        _registry().diff("経費精算規程", "v1", "v9")


def test_diff_unknown_document_raises():
    with pytest.raises(KeyError):
        _registry().diff("存在しない規程", "v1", "v2")


def test_versions_are_ordered_by_registration():
    assert _registry().versions("経費精算規程") == ["v1", "v2"]
