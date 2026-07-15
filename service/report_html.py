"""承認状況 HTMLレポート(標準ライブラリのみ)."""
from __future__ import annotations

import html
from typing import List, Dict

_STATUS_LABEL = {"draft": "下書き", "submitted": "申請中", "approved": "承認済", "rejected": "却下"}


def build_html_report(approvals: List[Dict]) -> str:
    rows = ""
    for a in approvals:
        rows += (f'<tr><td>{html.escape(a["req_id"])}</td><td>{html.escape(a["title"])}</td>'
                 f'<td>{html.escape(a["requester"])}</td><td>{html.escape(a.get("approver", ""))}</td>'
                 f'<td>{_STATUS_LABEL.get(a["status"], a["status"])}</td></tr>')
    return f"""<!DOCTYPE html><html lang="ja"><head><meta charset="UTF-8">
<title>承認状況レポート</title>
<style>body{{font-family:system-ui,sans-serif;margin:24px;color:#1a1a2e}}
h1{{color:#c0562b}} table{{border-collapse:collapse;width:100%}}
th,td{{border:1px solid #dde;padding:6px 10px}} th{{background:#fbeee7}}</style></head><body>
<h1>承認状況レポート</h1>
<table><tr><th>申請ID</th><th>件名</th><th>申請者</th><th>決裁者</th><th>状態</th></tr>{rows}</table>
<p><small>※全ての承認操作は監査ログに記録されます。</small></p>
</body></html>"""
