"""日本語テキスト正規化とトークン化(検索・金額抽出の共通基盤).

設計意図:
  - 表記ゆれ(全角/半角, 大小文字, 異体の空白)を NFKC で吸収する。
  - 助詞などの機能語をノイズとして持ち込まないため、**ひらがなを区切り文字**として扱い、
    漢字/カタカナ/英数字の連なり(= 内容語セグメント)からのみトークンを作る。
  - 数字は桁ゆれ(5万/8万/20日/25日)で検索が外れないよう `0` に正規化する。
    金額の意味判定は policy.py が別途、正規化前の原文に対して行う。

このモジュールは外部依存を持たない(標準ライブラリのみ)。
"""
from __future__ import annotations

import re
import unicodedata
from typing import List

# 内容語セグメント: 漢字 / カタカナ / 英数字 / 長音符・繰り返し記号
_SEGMENT_RE = re.compile(
    r"[一-鿿㐀-䶵々〆ヵヶ]+"          # 漢字(CJK統合漢字 + 拡張A) と々〆
    r"|[ァ-ヴー]+"                    # カタカナ
    r"|[a-z0-9]+"                     # 英数字(NFKC + lower 済み前提)
)
_DIGITS_RE = re.compile(r"[0-9]+")
_LATIN_RE = re.compile(r"^[a-z0-9]+$")

# 疑問詞に使われる漢字は「内容語」ではなく区切りとして扱う。
# 「週何日まで？」「誰の承認？」を語彙外語(=答えられない論点)と誤判定しないため。
_INTERROGATIVE_RE = re.compile(r"[何誰幾]")


def normalize(text: str) -> str:
    """NFKC 正規化 + 小文字化. 全角英数字・全角記号を半角へ寄せる."""
    if not text:
        return ""
    return unicodedata.normalize("NFKC", text).lower()


def _mask_digits(text: str) -> str:
    """数字列を単一の 0 に潰す(8万円 と 5万円 を同じ語形として扱うため)."""
    return _DIGITS_RE.sub("0", text)


def content_tokens(text: str) -> List[str]:
    """内容語トークン(検索用)を返す.

    - ひらがなは区切り文字として捨てる(助詞・語尾のノイズを排除)
    - 漢字/カタカナのセグメントは文字 bigram(1文字なら unigram)
    - 英数字のセグメントは語そのもの
    - 数字は 0 に正規化
    """
    norm = _INTERROGATIVE_RE.sub(" ", _mask_digits(normalize(text)))
    tokens: List[str] = []
    for seg in _SEGMENT_RE.findall(norm):
        if _LATIN_RE.match(seg):
            tokens.append(seg)
            continue
        if len(seg) == 1:
            tokens.append(seg)
        else:
            tokens.extend(seg[i:i + 2] for i in range(len(seg) - 1))
    return tokens


# 後方互換: 旧 API 名。挙動は content_tokens に統一されている。
def tokenize(text: str) -> List[str]:
    return content_tokens(text)
