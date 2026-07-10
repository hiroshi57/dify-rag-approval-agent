"""Slack 通知連携. webhook 未設定時は outbox に貯める dry-run(テスト/ローカル用)."""
from __future__ import annotations

import json
from typing import List, Optional


class SlackNotifier:
    def __init__(self, webhook_url: Optional[str] = None) -> None:
        self.webhook_url = webhook_url
        self.outbox: List[str] = []   # dry-run 時の送信済みメッセージ

    def notify(self, message: str) -> bool:
        if not self.webhook_url:
            self.outbox.append(message)   # dry-run
            return False
        import urllib.request
        data = json.dumps({"text": message}).encode("utf-8")
        req = urllib.request.Request(
            self.webhook_url, data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            return 200 <= resp.status < 300
