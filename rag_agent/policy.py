"""承認ルーティング規程. 金額に応じて必要な承認者レベルを決定する.

サンプル規程(docs/expense_policy.md 第4条): 5万円を超える経費は部長承認を必要とする。

金額抽出は承認レベルを左右するため、**過少判定(under-approval)を出さない**ことを
最優先に設計している。
  - 「5万1000円」を 50,000 円と読んで上長承認に落とすような複合表記の取りこぼしを防ぐ
  - 複数の金額が書かれている場合は最大値を採用する(安全側)
  - 解釈できない/符号が付く/桁が異常な場合は自動決裁せず人手確認へ倒す(fail-closed)
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import List, Optional

# 桁単位付きの数値が連なる表記(例: 1万5000円 / 1億2000万円 / 0.5万円 / 120,000円)
_MAGNITUDE = {"億": 100_000_000, "万": 10_000, "千": 1_000}
_NUM_GROUP = r"[0-9][0-9,]*(?:\.[0-9]+)?(?:億|万|千)?"
_AMOUNT_WITH_YEN = re.compile(rf"(?:{_NUM_GROUP})+\s*円")
_AMOUNT_MAGNITUDE_ONLY = re.compile(r"[0-9][0-9,]*(?:\.[0-9]+)?(?:億|万|千)")
_GROUP_RE = re.compile(r"([0-9][0-9,]*(?:\.[0-9]+)?)(億|万|千)?")
_SIGN_CHARS = "-−▲△"

# 漢数字表記(例: 五万円 / 十万円)
_KANJI_DIGITS = {"〇": 0, "零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
                 "六": 6, "七": 7, "八": 8, "九": 9}
_KANJI_SMALL_UNITS = {"十": 10, "百": 100, "千": 1000}
_KANJI_BIG_UNITS = {"万": 10_000, "億": 100_000_000}
_KANJI_AMOUNT_RE = re.compile(r"[〇零一二三四五六七八九十百千万億]+\s*円")

# 常識的な上限(これを超える自動決裁はしない)
SANITY_MAX_YEN = 10_000_000_000


@dataclass
class AmountExtraction:
    """抽出結果. amount は「安全側(最大)」の解釈."""
    amount: Optional[int]
    candidates: List[int] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"amount": self.amount, "candidates": self.candidates,
                "warnings": self.warnings}


def _parse_kanji_number(s: str) -> Optional[int]:
    total, section, digit, seen = 0, 0, 0, False
    for ch in s:
        if ch in _KANJI_DIGITS:
            digit = _KANJI_DIGITS[ch]
            seen = True
        elif ch in _KANJI_SMALL_UNITS:
            section += (digit or 1) * _KANJI_SMALL_UNITS[ch]
            digit, seen = 0, True
        elif ch in _KANJI_BIG_UNITS:
            section += digit
            total += (section or 1) * _KANJI_BIG_UNITS[ch]
            section, digit, seen = 0, 0, True
        else:
            return None
    return total + section + digit if seen else None


def _parse_number_expr(expr: str) -> Optional[int]:
    """「1万5000」「0.5万」「120,000」を円に変換する."""
    total = 0.0
    matched_any = False
    pos = 0
    for m in _GROUP_RE.finditer(expr):
        if m.start() != pos:          # 想定外の文字が挟まる場合は解釈しない
            return None
        pos = m.end()
        matched_any = True
        value = float(m.group(1).replace(",", ""))
        total += value * _MAGNITUDE.get(m.group(2) or "", 1)
    if not matched_any or pos != len(expr):
        return None
    return int(round(total))


def extract_amounts(text: str) -> AmountExtraction:
    """本文から金額(円)候補を抽出する. 安全側として最大値を amount に採る."""
    if not text:
        return AmountExtraction(amount=None, warnings=["金額の記載がありません"])
    norm = unicodedata.normalize("NFKC", text)

    candidates: List[int] = []
    warnings: List[str] = []
    spans: List[tuple] = []

    def _collect(m: re.Match, value: Optional[int]) -> None:
        if value is None:
            warnings.append(f"金額表記を解釈できませんでした: {m.group(0)!r}")
            return
        prev = norm[:m.start()].rstrip()
        if prev and prev[-1] in _SIGN_CHARS:
            warnings.append(f"負号付きの金額は自動判定しません: {m.group(0)!r}")
            return
        if value > SANITY_MAX_YEN:
            warnings.append(f"金額が上限({SANITY_MAX_YEN:,}円)を超えています: {m.group(0)!r}")
            return
        candidates.append(value)
        spans.append((m.start(), m.end()))

    for m in _AMOUNT_WITH_YEN.finditer(norm):
        _collect(m, _parse_number_expr(m.group(0)[:-1].strip().rstrip("円").strip()))
    for m in _KANJI_AMOUNT_RE.finditer(norm):
        _collect(m, _parse_kanji_number(m.group(0)[:-1].strip()))
    # 「3万の交通費」のように円が省略された表記(既存表記の救済)
    for m in _AMOUNT_MAGNITUDE_ONLY.finditer(norm):
        if any(s <= m.start() < e for s, e in spans):
            continue
        _collect(m, _parse_number_expr(m.group(0)))

    if not candidates:
        warnings.append("金額を抽出できませんでした")
        return AmountExtraction(amount=None, warnings=warnings)
    if len(set(candidates)) > 1:
        warnings.append(f"複数の金額が検出されたため最大値を採用しました: {sorted(set(candidates))}")
    return AmountExtraction(amount=max(candidates), candidates=sorted(set(candidates)),
                            warnings=warnings)


def extract_amount(text: str) -> Optional[int]:
    """後方互換 API. 詳細が必要な場合は extract_amounts を使う."""
    return extract_amounts(text).amount


@dataclass
class ApprovalRoute:
    required_approver: str            # 上長 / 部長
    reason: str
    amount: Optional[int] = None
    requires_manual_review: bool = False   # 自動決裁してはいけない(人手確認が必要)
    rule_ref: str = ""

    def as_dict(self) -> dict:
        return {"required_approver": self.required_approver, "reason": self.reason,
                "amount": self.amount, "requires_manual_review": self.requires_manual_review,
                "rule_ref": self.rule_ref}


class ApprovalPolicy:
    """金額から承認者を決定する.

    unknown_amount:
      - "escalate"(既定): 金額不明は上位承認者へ倒し、人手確認フラグを立てる(fail-closed)
      - "supervisor": 金額不明でも上長承認とする(旧挙動。監査要件が緩い場合のみ)
    """

    MANAGER = "部長"
    SUPERVISOR = "上長"

    def __init__(self, manager_threshold: int = 50000,
                 unknown_amount: str = "escalate",
                 rule_ref: str = "経費精算規程 第4条") -> None:
        if manager_threshold < 0:
            raise ValueError("manager_threshold は 0 以上で指定してください")
        if unknown_amount not in ("escalate", "supervisor"):
            raise ValueError("unknown_amount は 'escalate' か 'supervisor'")
        self.manager_threshold = manager_threshold
        self.unknown_amount = unknown_amount
        self.rule_ref = rule_ref

    def route(self, amount: Optional[int]) -> ApprovalRoute:
        if amount is None:
            if self.unknown_amount == "escalate":
                return ApprovalRoute(self.MANAGER, "金額を特定できないため部長承認＋人手確認が必要",
                                     None, True, self.rule_ref)
            return ApprovalRoute(self.SUPERVISOR, "金額不明のため上長承認", None, True,
                                 self.rule_ref)
        if amount < 0:
            return ApprovalRoute(self.MANAGER, "金額が負値のため自動判定不可(人手確認)",
                                 amount, True, self.rule_ref)
        if amount > self.manager_threshold:
            return ApprovalRoute(
                self.MANAGER,
                f"{amount:,}円は{self.manager_threshold:,}円超のため部長承認が必要",
                amount, False, self.rule_ref)
        return ApprovalRoute(self.SUPERVISOR, f"{amount:,}円は上長承認で可",
                             amount, False, self.rule_ref)

    def route_text(self, text: str) -> ApprovalRoute:
        """本文から金額を抽出してルーティングする(抽出時の警告も理由に含める)."""
        ex = extract_amounts(text)
        route = self.route(ex.amount)
        if ex.warnings:
            route.reason = f"{route.reason}（注記: {'; '.join(ex.warnings)}）"
            if any("解釈できません" in w or "負号" in w or "上限" in w for w in ex.warnings):
                route.requires_manual_review = True
        return route
