import os

import pytest

from rag_agent import (
    DocumentStore, ingest_markdown, ingest_dir, Retriever, QAAgent, AuditLog, Answer,
    Citation, RegulationRegistry,
)

POLICY = """# 経費精算規程
第3条（締め日）
経費精算の締め日は毎月20日とする。
第5条（証憑）
経費申請には領収書等の証憑の添付を必須とする。
本条は第3条の規定にかかわらず適用され、証憑の不備がある場合は差し戻しの対象となる。
"""


def _agent(audit=None, **kw):
    store = DocumentStore(ingest_markdown(POLICY, doc_id="expense_policy", version="v1"))
    return QAAgent(Retriever(store), audit=audit or AuditLog(), **kw)


# --- 取込 ---
def test_ingest_splits_by_article():
    chunks = ingest_markdown(POLICY, doc_id="expense_policy")
    sections = {c.section_id for c in chunks}
    assert "第3条" in sections
    assert "第5条" in sections


def test_ingest_picks_document_title_from_h1():
    chunks = ingest_markdown(POLICY, doc_id="expense_policy")
    assert all(c.doc_title == "経費精算規程" for c in chunks)
    # 引用は「ファイル名」ではなく「規程名 + 条番号」で出す
    third = next(c for c in chunks if c.section_id == "第3条")
    assert third.citation == "経費精算規程 第3条"


def test_ingest_keeps_heading_text_in_body():
    chunks = ingest_markdown("## 在宅勤務のルール\n週3日まで可能です。\n", doc_id="faq")
    assert "在宅勤務" in chunks[0].text


def test_ingest_does_not_split_on_inline_article_reference():
    """本文中の「第3条の規定にかかわらず」で誤って章立てしない."""
    chunks = ingest_markdown(POLICY, doc_id="expense_policy")
    assert [c.section_id for c in chunks].count("第3条") == 1


def test_ingest_ignores_fenced_code_block():
    text = "# 規程\n第1条（目的）\n本文\n```\n第9条（コード内の見出しに見える行）\n```\n"
    sections = [c.section_id for c in ingest_markdown(text, doc_id="d")]
    assert "第9条" not in sections


def test_version_is_attached_to_citation():
    chunks = ingest_markdown(POLICY, doc_id="expense_policy", version="v2")
    assert chunks[0].citation.endswith("(v2)")


def test_ingest_dir_reads_sample_docs():
    docs_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs")
    chunks = ingest_dir(docs_dir)
    assert len(chunks) >= 5


# --- 引用必須 ---
def test_answer_includes_citation():
    a = _agent().ask("経費精算の締め日はいつ？")
    assert a.answered is True
    assert a.citations, "引用が必須"
    assert any(c.section_id == "第3条" for c in a.citations)
    assert "20日" in a.text
    assert a.citations[0].doc_title == "経費精算規程"


def test_refuses_when_no_relevant_doc():
    a = _agent().ask("社員旅行の積立金の金額は？")
    assert a.answered is False
    assert a.citations == []
    assert a.refusal_reason in ("no_hit", "out_of_scope", "low_score")


def test_refuses_empty_question():
    a = _agent().ask("   ")
    assert a.answered is False and a.refusal_reason == "empty_query"


def test_answered_answer_cannot_be_built_without_citation():
    """不変条件をデータ構造レベルで強制している(テストの外でも壊れない)."""
    with pytest.raises(ValueError):
        Answer(answered=True, text="根拠なし回答", citations=[])
    with pytest.raises(ValueError):
        Answer(answered=False, text="拒否", citations=[Citation("d", "s", "t")])


def test_citation_never_empty_when_answered():
    agent = _agent()
    answered_any = False
    for q in ["締め日", "証憑", "領収書"]:
        a = agent.ask(q)
        assert a.answered, f"想定質問に回答できていない: {q}"
        answered_any = True
        assert len(a.citations) >= 1
    assert answered_any


def test_qa_is_audited_with_reason():
    audit = AuditLog()
    agent = _agent(audit=audit)
    agent.ask("締め日は？")
    agent.ask("宇宙の年齢は？")
    actions = [e.action for e in audit.entries]
    assert "qa.answered" in actions
    assert "qa.refused" in actions
    refused = audit.filter("qa.refused")[0]
    assert refused.detail["reason"]
    assert audit.verify() is True


def test_stale_citation_is_flagged_in_answer():
    """陳腐化検知が QA 経路に実際につながっていること(旧実装ではデッドコードだった)."""
    reg = RegulationRegistry()
    reg.register("expense_policy", "v1", {"第3条": "締め日は毎月20日"})
    reg.register("expense_policy", "v2", {"第3条": "締め日は毎月25日"})
    a = _agent(registry=reg).ask("締め日は？")
    assert a.answered is True
    assert a.stale_citations and a.stale_citations[0]["latest_version"] == "v2"
    assert "改定" in a.text


def test_threshold_validation():
    store = DocumentStore(ingest_markdown(POLICY, doc_id="d"))
    with pytest.raises(ValueError):
        QAAgent(Retriever(store), min_score=1.5)
    with pytest.raises(ValueError):
        QAAgent(Retriever(store), max_out_of_scope_ratio=-0.1)


def test_empty_corpus_refuses():
    agent = QAAgent(Retriever(DocumentStore()))
    a = agent.ask("締め日は？")
    assert a.answered is False and a.refusal_reason == "no_hit"
