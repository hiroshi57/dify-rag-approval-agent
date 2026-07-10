import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rag_agent import (  # noqa: E402
    DocumentStore, ingest_markdown, ingest_dir, Retriever, QAAgent, AuditLog,
)

POLICY = """# 経費精算規程
第3条（締め日）
経費精算の締め日は毎月20日とする。
第5条（証憑）
経費申請には領収書等の証憑の添付を必須とする。
"""


def _agent(audit=None):
    store = DocumentStore()
    store.extend(ingest_markdown(POLICY, doc_id="経費精算規程"))
    return QAAgent(Retriever(store), audit=audit or AuditLog())


def test_ingest_splits_by_article():
    chunks = ingest_markdown(POLICY, doc_id="経費精算規程")
    sections = {c.section_id for c in chunks}
    assert "第3条" in sections
    assert "第5条" in sections


def test_answer_includes_citation():
    a = _agent().ask("経費精算の締め日はいつ？")
    assert a.answered is True
    assert a.citations, "引用が必須"
    assert any(c.section_id == "第3条" for c in a.citations)
    assert "20日" in a.text


def test_refuses_when_no_relevant_doc():
    a = _agent().ask("社員旅行の積立金の金額は？")
    assert a.answered is False
    assert a.citations == []          # 根拠なしでは引用ゼロ
    assert "見つかりません" in a.text


def test_citation_never_empty_when_answered():
    # 引用必須の不変条件: answered ならば citations は非空
    agent = _agent()
    for q in ["締め日", "証憑", "領収書"]:
        a = agent.ask(q)
        if a.answered:
            assert len(a.citations) >= 1


def test_qa_is_audited():
    audit = AuditLog()
    agent = _agent(audit=audit)
    agent.ask("締め日は？")
    agent.ask("宇宙の年齢は？")
    actions = [e.action for e in audit.entries]
    assert "qa.answered" in actions
    assert "qa.refused" in actions


def test_ingest_dir_reads_sample_docs():
    docs_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs")
    chunks = ingest_dir(docs_dir)
    assert len(chunks) >= 5
