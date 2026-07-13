"""承認ルーティング規程. 金額に応じて必要な承認者レベルを決定する.

サンプル規程(docs/expense_policy.md 第4条): 5万円を超える経費は部長承認を必要とする。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

_AMOUNT_RE = re.compile(r"(\d[\d,]*)\s*(万円|万|円)")


def extract_amount(text: str) -> Optional[int]:
    """本文から金額(円)を抽出. 「5万円」「50000円」等に対応."""
    m = _AMOUNT_RE.search(text)
    if not m:
        return None
    val = int(m.group(1).replace(",", ""))
    if m.group(2) in ("万円", "万"):
        val *= 10000
    return val


@dataclass
class ApprovalRoute:
    required_approver: str   # 上長 / 部長
    reason: str


class ApprovalPolicy:
    def __init__(self, manager_threshold: int = 50000) -> None:
        self.manager_threshold = manager_threshold

    def route(self, amount: Optional[int]) -> ApprovalRoute:
        if amount is not None and amount > self.manager_threshold:
            return ApprovalRoute("部長",
                                 f"{amount:,}円は{self.manager_threshold:,}円超のため部長承認が必要")
        return ApprovalRoute("上長",
                             f"{amount:,}円は上長承認で可" if amount is not None else "金額不明のため上長承認")
