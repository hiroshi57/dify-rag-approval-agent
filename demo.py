"""デモ(ネットワーク/APIキー不要). `python demo.py`"""
import os

from rag_agent import (
    DocumentStore, ingest_dir, Retriever, QAAgent,
    ApprovalStore, detect_approval_intent, AuditLog, SlackNotifier,
)

DOCS = os.path.join(os.path.dirname(__file__), "docs")


def main():
    audit = AuditLog()
    store = DocumentStore()
    store.extend(ingest_dir(DOCS))
    print(f"取込チャンク数: {len(store)}")

    agent = QAAgent(Retriever(store), audit=audit)

    print("\n=== Q&A(引用必須) ===")
    for q in ["経費精算の締め日はいつ？", "有給休暇はどう申請する？", "社員旅行の積立金は？"]:
        a = agent.ask(q, actor="user01")
        print(f"\nQ: {q}")
        if a.answered:
            print(f"A: {a.text}")
            print(f"   出典: {[c.section_id for c in a.citations]}")
        else:
            print(f"A(拒否): {a.text}")

    print("\n=== 承認ルーティング(規程第4条: 5万円超は部長) ===")
    from rag_agent import ApprovalPolicy, extract_amount
    policy = ApprovalPolicy()
    for msg in ["3万円の交通費を精算したい", "備品を8万円で購入申請"]:
        amt = extract_amount(msg)
        route = policy.route(amt)
        print(f"  「{msg}」-> 金額{amt}円 承認者={route.required_approver}({route.reason})")

    print("\n=== 承認申請フロー ===")
    approvals = ApprovalStore(notifier=SlackNotifier(), audit=audit)
    msg = "出張費5万円を経費精算したい"
    print(f"ユーザー発話: {msg} -> 申請意図検知: {detect_approval_intent(msg)}")
    req = approvals.create("user01", "出張費精算", msg)
    approvals.submit(req.id)
    approvals.decide(req.id, approver="manager01", approve=True)
    print(f"申請 {req.id} 最終状態: {approvals.get(req.id).status}")
    print(f"Slack送信(dry-run outbox): {len(approvals.notifier.outbox)}件")

    print("\n=== 監査ログ ===")
    for e in audit.entries:
        print(f"  {e.action:22} actor={e.actor}")


if __name__ == "__main__":
    main()
