"""Direct Python client: simplest path for Jupyter researchers."""

from qianji_data_mini import Database


database = Database()
frame = database.query_dataframe(
    symbol="000001.SZ",
    start_date="2026-08-01",
    end_date="2026-08-31",
    source="auto",
)
print(frame.tail())

