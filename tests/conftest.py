import os
import sys

# リポジトリルートを import パスに追加(各テストでの sys.path 操作をやめて一元化)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
