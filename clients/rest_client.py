"""REST client for a separately running qianji-data serve process."""

import os

import pandas as pd
import requests


headers = {}
if os.getenv("QIANJI_API_KEY"):
    headers["X-API-Key"] = os.environ["QIANJI_API_KEY"]

response = requests.get(
    "http://127.0.0.1:8765/v1/equity/price/historical",
    params={
        "symbol": "000001.SZ",
        "start_date": "2026-08-01",
        "end_date": "2026-08-31",
        "source": "auto",
    },
    headers=headers,
    timeout=30,
)
response.raise_for_status()
print(pd.DataFrame(response.json()["results"]).tail())

