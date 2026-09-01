"""Read-only environment check. It does not log in or consume vendor quota."""

import importlib.util
import os
import sys

from qianji_data_mini.db import Database


def module_ready(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


rows = [
    ("Python", True, sys.version.split()[0]),
    ("SQLite", True, str(Database().path)),
    ("Tushare SDK", module_ready("tushare"), "pip 包"),
    ("Tushare Token", bool(os.getenv("TUSHARE_TOKEN")), "TUSHARE_TOKEN"),
    ("iFinD refresh_token", bool(os.getenv("IFIND_REFRESH_TOKEN")), "IFIND_REFRESH_TOKEN"),
    ("WindPy", module_ready("WindPy"), "由 Wind 客户端安装"),
    ("EmQuantAPI", module_ready("EmQuantAPI"), "由 Choice 接口包安装"),
    ("OpenBB", module_ready("openbb"), "可选安装"),
]

width = max(len(name) for name, _, _ in rows)
for name, ready, note in rows:
    print(f"{name:<{width}}  {'可用' if ready else '未就绪'}  {note}")

