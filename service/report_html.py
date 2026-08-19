"""承認状況 HTMLレポート(標準ライブラリのみ). 全ての動的値をエスケープする."""
from __future__ import annotations

import html
from datetime import datetime, timezone
from typing import Dict, List, Optional

_STATUS_LABEL = {"draft": "下書き", "submitted": "申請中", "approved": "承認済",
                 "rejected": "却下", "cancelled": "取消"}


def _esc(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _status_label(status: str) -> str:
    # 未知のステータスも必ずエスケープしてから出す(ラベル辞書に無い値の素通しを防ぐ)
    return _esc(_STATUS_LABEL.get(status, status))


def _amount(value) -> str:
    try:
        return f"{int(value):,}円"
    except (TypeError, ValueError):
        return "-"


def build_html_report(approvals: List[Dict], tenant_id: str = "",
                      generated_at: Optional[str] = None) -> str:
    counts: Dict[str, int] = {}
    rows = ""
    for a in approvals:
        status = str(a.get("status", ""))
        counts[status] = counts.get(status, 0) + 1
        flag = "⚠ 要確認" if a.get("requires_manual_review") else ""
        rows += (
            f'<tr><td>{_esc(a.get("req_id"))}</td>'
            f'<td>{_esc(a.get("title"))}</td>'
            f'<td>{_esc(a.get("requester"))}</td>'
            f'<td>{_esc(a.get("required_approver") or a.get("approver"))}</td>'
            f'<td>{_esc(a.get("approver"))}</td>'
            f'<td class="num">{_amount(a.get("amount"))}</td>'
            f'<td>{_status_label(status)}</td>'
            f'<td>{_esc(flag)}</td></tr>')
    if not rows:
        rows = '<tr><td colspan="8" class="empty">対象の承認申請はありません</td></tr>'

    summary = "／".join(f"{_status_label(k)}: {v}件" for k, v in sorted(counts.items())) or "-"
    ts = generated_at or datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    tenant = f"（テナント: {_esc(tenant_id)}）" if tenant_id else ""

    return f"""<!DOCTYPE html><html lang="ja"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
<title>承認状況レポート</title>
<style>body{{font-family:system-ui,sans-serif;margin:24px;color:#1a1a2e}}
h1{{color:#c0562b;font-size:20px}} table{{border-collapse:collapse;width:100%;font-size:14px}}
th,td{{border:1px solid #dde;padding:6px 10px;text-align:left}} th{{background:#fbeee7}}
td.num{{text-align:right}} td.empty{{text-align:center;color:#889}}
p.meta{{color:#667;font-size:12px}}</style></head><body>
<h1>承認状況レポート{tenant}</h1>
<p class="meta">生成日時: {_esc(ts)} ／ 件数: {len(approvals)}件 ／ 内訳: {summary}</p>
<table><tr><th>申請ID</th><th>件名</th><th>申請者</th><th>必要承認者</th><th>決裁者</th>
<th>金額</th><th>状態</th><th>備考</th></tr>{rows}</table>
<p><small>※全ての承認操作は監査ログ(ハッシュチェーン付き)に記録されます。</small></p>
</body></html>"""
