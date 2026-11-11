"""应用配置。"""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
STORE_PATH = DATA_DIR / "store.json"

# 抓取参数
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "10.0"))
MAX_PAGES = int(os.getenv("MAX_PAGES", "100"))          # 分页上限，防止异常链接导致死循环
MAX_CONCURRENCY = int(os.getenv("MAX_CONCURRENCY", "8"))  # 详情页并发数
USER_AGENT = os.getenv("USER_AGENT", "tender-collector/1.0 (+local)")

# 离线样例目录（由 API 静态挂载）
SAMPLE_DIR = BASE_DIR / "sample_site"
