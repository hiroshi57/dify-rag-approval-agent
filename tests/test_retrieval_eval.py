"""検索ゲートの評価セット.

「引用必須で誤答しない」という主張は、**答えるべき質問に答えられ、
答えるべきでない質問を断れる**ことでしか検証できない。
旧実装は後者(false positive)のテストが無く、
規程に無い論点(副業・海外株取引など)にも無関係な条文を返していた。

このテストは閾値(DEFAULT_MIN_SCORE / DEFAULT_MAX_OOS_RATIO)を
経験的に固定するための回帰テストでもある。
"""
import os

import pytest

from rag_agent import DocumentStore, QAAgent, Retriever, ingest_dir

DOCS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs")

SHOULD_ANSWER = [
    "経費精算の締め日はいつ？",
    "有給休暇はどう申請する？",
    "在宅勤務は週何日まで？",
    "8万円の経費は誰の承認が必要？",
    "領収書は必要ですか",
    "備品購入の依頼方法",
    "経費精算はどこから申請しますか",
    "締め日",
]

SHOULD_REFUSE = [
    "社員旅行の積立金の金額は？",
    "宇宙の年齢は？",
    "在宅勤務中に副業してよいですか",
    "有給休暇中に海外で株取引しても良い？",
    "経費で高級腕時計を買っても精算できますか",
    "来月の忘年会の予算は？",
    "退職金の計算方法は？",
    "育児休業は何年取れますか",
]


@pytest.fixture(scope="module")
def agent():
    return QAAgent(Retriever(DocumentStore(ingest_dir(DOCS))))


@pytest.mark.parametrize("q", SHOULD_ANSWER)
def test_answers_in_scope_questions(agent, q):
    a = agent.ask(q)
    assert a.answered is True, f"答えられるはずの質問を拒否した: {q}"
    assert a.citations


@pytest.mark.parametrize("q", SHOULD_REFUSE)
def test_refuses_out_of_scope_questions(agent, q):
    a = agent.ask(q)
    assert a.answered is False, f"規程に無い論点に回答してしまった: {q} -> {a.text[:60]}"
    assert a.citations == []


def test_out_of_scope_terms_are_reported(agent):
    a = agent.ask("在宅勤務中に副業してよいですか")
    assert a.refusal_reason == "out_of_scope"
    assert any("副業" in t for t in a.out_of_scope_terms)


def test_scores_are_deterministic(agent):
    first = [(h.chunk.citation, round(h.score, 6)) for h in agent.retriever.retrieve("締め日")]
    second = [(h.chunk.citation, round(h.score, 6)) for h in agent.retriever.retrieve("締め日")]
    assert first == second


def test_idf_weighting_prefers_specific_terms(agent):
    r = agent.retriever
    # コーパス全体に出る語より、限定的な語のほうが重い
    assert r.idf("証憑") > r.idf("経費")
    assert r.idf("存在しない語") > r.idf("証憑")
