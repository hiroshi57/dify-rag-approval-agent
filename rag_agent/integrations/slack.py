"""Slack 通知連携. webhook 未設定時は outbox に貯める dry-run(テスト/ローカル用).

セキュリティ:
  - webhook URL は https かつ許可ホストのみ(SSRF / 誤送信の抑止)
  - 例外を握り潰さず NotifyResult で結果を返す(呼び出し側が監査に残せる)
  - タイムアウトと簡易リトライを備える
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import List, Optional, Tuple

ALLOWED_HOSTS: Tuple[str, ...] = ("hooks.slack.com",)
MAX_MESSAGE_CHARS = 3000


@dataclass
class NotifyResult:
    delivered: bool
    dry_run: bool = False
    status: Optional[int] = None
    detail: str = ""

    def __bool__(self) -> bool:
        return self.delivered


class SlackNotifier:
    def __init__(self, webhook_url: Optional[str] = None, timeout: float = 5.0,
                 retries: int = 2, allowed_hosts: Tuple[str, ...] = ALLOWED_HOSTS) -> None:
        self.webhook_url = webhook_url or None
        self.timeout = timeout
        self.retries = max(retries, 0)
        self.allowed_hosts = allowed_hosts
        self.outbox: List[str] = []      # dry-run 時の送信済みメッセージ
        if self.webhook_url:
            self._validate(self.webhook_url)

    def _validate(self, url: str) -> None:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https":
            raise ValueError("Slack webhook は https のみ許可します")
        if self.allowed_hosts and parsed.hostname not in self.allowed_hosts:
            raise ValueError(
                f"許可されていない webhook ホストです: {parsed.hostname} "
                f"(許可: {', '.join(self.allowed_hosts)})")

    @property
    def is_dry_run(self) -> bool:
        return not self.webhook_url

    def notify(self, message: str) -> NotifyResult:
        text = (message or "")[:MAX_MESSAGE_CHARS]
        if self.is_dry_run:
            self.outbox.append(text)
            return NotifyResult(delivered=False, dry_run=True, detail="webhook 未設定(dry-run)")

        data = json.dumps({"text": text}).encode("utf-8")
        last_detail = ""
        for attempt in range(self.retries + 1):
            req = urllib.request.Request(
                self.webhook_url, data=data,
                headers={"Content-Type": "application/json"}, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310
                    ok = 200 <= resp.status < 300
                    if ok:
                        return NotifyResult(delivered=True, status=resp.status)
                    last_detail = f"HTTP {resp.status}"
            except urllib.error.HTTPError as exc:
                last_detail = f"HTTP {exc.code}"
                if 400 <= exc.code < 500:          # クライアントエラーは再試行しない
                    break
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_detail = f"{type(exc).__name__}: {exc}"
            if attempt < self.retries:
                time.sleep(min(0.5 * (2 ** attempt), 2.0))
        return NotifyResult(delivered=False, detail=last_detail or "unknown error")
