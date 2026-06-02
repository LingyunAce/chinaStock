"""项目级 pytest 配置。

把项目根目录加入 sys.path，让测试可以 `from src.xxx import yyy`。
所有 test_*.py 不再需要自己做 sys.path.insert。
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
