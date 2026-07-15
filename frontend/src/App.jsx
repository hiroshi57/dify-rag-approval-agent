import React, { useState } from "react";
import ChatConsole from "./screens/ChatConsole.jsx";
import ApprovalConsole from "./screens/ApprovalConsole.jsx";
import { ask, createApproval, reportUrl } from "./api.js";

const TENANT = "demo-tenant";
const DEMO_ANSWER = {
  answered: true, text: "第3条（締め日） 経費精算の締め日は毎月20日とする。",
  citations: [{ doc_id: "経費精算規程", section_id: "第3条" }],
};

export default function App() {
  const [tab, setTab] = useState("chat");
  const [answer, setAnswer] = useState(DEMO_ANSWER);
  const [approval, setApproval] = useState(null);
  const [busy, setBusy] = useState(false);

  const onAsk = async (q) => {
    setBusy(true);
    try { setAnswer(await ask(TENANT, q)); }
    catch (e) { alert("バックエンド未起動の可能性: " + e.message); }
    finally { setBusy(false); }
  };
  const onCreate = async (req) => {
    try { setApproval(await createApproval(TENANT, req)); }
    catch (e) { alert("バックエンド未起動の可能性: " + e.message); }
  };

  return (
    <div className="wrap">
      <h1>社内規程RAG + 承認エージェント</h1>
      <nav>
        <button onClick={() => setTab("chat")} disabled={tab === "chat"}>規程チャット</button>
        <button onClick={() => setTab("approval")} disabled={tab === "approval"}>承認コンソール</button>
      </nav>
      {tab === "chat"
        ? <ChatConsole onAsk={onAsk} answer={answer} busy={busy} />
        : <ApprovalConsole onCreate={onCreate} result={approval}
            onOpenReport={() => window.open(reportUrl(), "_blank")} />}
    </div>
  );
}
