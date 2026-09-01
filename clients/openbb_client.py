"""OpenBB client. Install the [openbb] extra and run openbb-build first."""

from openbb import obb


result = obb.equity.price.historical(
    symbol="000001.SZ",
    start_date="2026-08-01",
    end_date="2026-08-31",
    provider="qianji",
    source="auto",
)
print(result.to_dataframe().tail())

