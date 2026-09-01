"""千际轻量金融数据基座。"""

from qianji_data_mini.db import Database
from qianji_data_mini.ingest import ingest_daily

__all__ = ["Database", "ingest_daily"]
__version__ = "0.1.0"

