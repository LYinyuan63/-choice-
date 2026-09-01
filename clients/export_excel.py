"""Excel export client."""

from pathlib import Path

from qianji_data_mini import Database


output = Path("qianji_market_data.xlsx").resolve()
Database().query_dataframe(symbol="000001.SZ", source="auto").to_excel(output, index=False)
print(output)

