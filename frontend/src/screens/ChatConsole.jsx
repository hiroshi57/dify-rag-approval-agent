import React, { useState } from "react";

// RAGチャット: 引用必須。根拠なしは回答拒否を明示。
export default function ChatConsole({ onAsk, answer, busy }) {
  const [q, setQ] = useState("経費精算の締め日は?");
  return (
    <div className="card">
      <h2>社内規程チャット（引用必須）</h2>
      <input style={{ width: "100%" }} value={q} onChange={(e) => setQ(e.target.value)} />
      <button className="primary" disabled={busy} onClick={() => onAsk(q)}>
        {busy ? "検索中..." : "質問する"}
      </button>
      {answer && (
        <div className={answer.answered ? "answer" : "refusal"}>
          <p>{answer.text}</p>
          {answer.answered && answer.citations?.length > 0 && (
            <div className="citations">出典: {answer.citations.map((c) => `${c.doc_id} ${c.section_id}`).join("、")}</div>
          )}
        </div>
      )}
    </div>
  );
}
