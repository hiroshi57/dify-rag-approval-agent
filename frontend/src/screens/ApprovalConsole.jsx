import React, { useState } from "react";

// 承認コンソール: 申請を起票。金額から承認者を自動ルーティング(5万円超->部長)。
export default function ApprovalConsole({ onCreate, result, onOpenReport }) {
  const [title, setTitle] = useState("出張費精算");
  const [detail, setDetail] = useState("出張費8万円を精算したい");
  return (
    <div className="card">
      <h2>承認申請</h2>
      <label>件名<input value={title} onChange={(e) => setTitle(e.target.value)} /></label>
      <label>内容（金額を含む）
        <input style={{ width: "100%" }} value={detail} onChange={(e) => setDetail(e.target.value)} /></label>
      <button className="primary" onClick={() => onCreate({ requester: "user01", title, detail })}>
        申請を起票
      </button>
      {result && (
        <div className="result">
          <p>{result.req_id}: <b>{result.required_approver}</b> 承認 → {result.status}</p>
          <p className="reason">{result.reason}</p>
        </div>
      )}
      {onOpenReport && <button onClick={onOpenReport}>承認状況レポート(HTML)</button>}
    </div>
  );
}
