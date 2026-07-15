# dify-rag-approval-agent

社内規程・FAQ を **RAG 検索して回答**し、会話から **承認申請フローを起票**できる社内向け AI エージェント。
Dify（LLM=Claude、内蔵ベクトルDB）を前提とし、本リポジトリには Dify 設定
（`dify-app/`, `workflows/`）と、その挙動の**リファレンス実装＋テスト**（`rag_agent/`）を含む。

## 差別化ポイント

一般的な社内 RAG ボットとの違い:

1. **引用必須（ハルシネーション抑止）** — 回答は必ず出典（規程名＋条番号）を伴う。
   関連スコアが閾値未満なら**推測せず「該当する規程が見つかりません」と回答を拒否**する。
   `answered=True` のとき `citations` が空になることはない（テストで担保）。
2. **監査ログ標準装備** — Q&A（回答/拒否）と承認操作（起票→提出→決裁）を追記専用ログに記録。
   「誰が・いつ・どの規程を根拠に・何を承認したか」を後から追跡できる。
3. **会話起点の承認フロー** — 発話から申請意図を検知し、`draft→submitted→approved/rejected`
   の状態機械で承認申請を管理。各遷移で Slack 通知＋監査記録。

いずれも **API キー・ネットワーク不要**（rule-based / dry-run）で動作する。

## MVP 3機能

| # | 機能 | 実装 |
|---|------|------|
| ① | ドキュメント取込（Markdown/PDF） | `rag_agent/ingest.py`（条番号・見出しでセクション分割） |
| ② | Q&A チャットボット（引用必須） | `rag_agent/agent.py` + `retriever.py` |
| ③ | Slack 通知連携 | `rag_agent/integrations/slack.py`（webhook 未設定時 dry-run） |

## 全機能(MVP＋拡張)

- ①ドキュメント取込 ②引用必須Q&A ③Slack通知（MVP）
- **承認ルーティング**（`policy.py`）: 規程第4条に基づき金額で承認者を自動判定（5万円超→部長）
- **マルチターン会話セッション**（`session.py`）
- **実行可能な FastAPI サービス**（`serve/api.py`）: `/v1/chat` `/v1/approvals` `/v1/audit`

## 本番構成（SQLite + HTMLレポート + Vite 2画面）

- **DB**: `service/db.py`（SQLite）。文書チャンク＋承認申請、全クエリ tenant_id 強制フィルタ＝**テナント分離**
- **API**: `service/api.py`（FastAPI）。docs(投入) / ask(引用必須QA) / approvals(金額ルーティング) / report(HTML)
- **HTMLレポート**: `service/report_html.py`（承認状況レポート、XSSエスケープ）
- **フロント**: `frontend/`（React+Vite）。**規程チャット**（引用必須・拒否表示）＋**承認コンソール**の2画面。ビルド不要は `frontend/standalone.html`
- **CI**: `.github/workflows/ci.yml`

```bash
uvicorn service.api:app --reload
cd frontend && npm install && npm run dev     # or: open frontend/standalone.html
python -m pytest -q                            # テスト23件(DB/テナント分離/HTMLレポート/API E2E含む)
```

## クイックスタート

```bash
python demo.py          # 取込→引用付きQ&A→拒否→承認ルーティング→承認フロー→監査ログ
python -m pytest -q     # テスト18件(外部依存なし)
uvicorn serve.api:app --reload   # Difyリファレンス実装のAPI起動
```

## 構成

```
rag_agent/
  ingest.py       # ① Markdown/PDF -> セクションチャンク(条番号抽出)
  store.py        # チャンク + 出典メタデータ
  retriever.py    # 外部依存なしの日本語対応検索(本番はDify内蔵VDBに置換)
  agent.py        # ② 引用必須Q&A(根拠なしは回答拒否)
  approval.py     # ③ 承認申請 状態機械
  audit.py        # 監査ログ(追記専用)
  integrations/slack.py  # Slack通知(dry-run対応)
dify-app/app.yaml           # Difyアプリ定義(Claude/引用必須プロンプト)
workflows/rag_approval_workflow.yaml  # Difyワークフロー(引用ゲート)
docs/                       # サンプル規程/FAQ
tests/                      # 引用必須・拒否・承認遷移を検証
```

## Dify への適用

`docs/` を Dify のナレッジに取込み、`dify-app/app.yaml` の設定
（`score_threshold`, 引用必須システムプロンプト）と `workflows/` の引用ゲートを反映する。
`rag_agent/` は同じ判定ロジックのリファレンス／回帰テストとして機能する。
