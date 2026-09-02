"""OpenBB provider registration for the company-owned SQLite database."""

from openbb_core.provider.abstract.provider import Provider

from qianji_data_mini.openbb_provider.equity_historical import (
    QianjiEquityHistoricalFetcher,
)
from qianji_data_mini.openbb_provider.equity_search import QianjiEquitySearchFetcher
from qianji_data_mini.openbb_provider.dividends import (
    QianjiHistoricalDividendsFetcher,
)
from qianji_data_mini.openbb_provider.financial_statements import (
    QianjiBalanceSheetFetcher,
    QianjiCashFlowStatementFetcher,
    QianjiIncomeStatementFetcher,
)


provider = Provider(
    name="qianji",
    description="Qianji standardized local financial database.",
    website="https://docs.openbb.co/",
    fetcher_dict={
        "EquityHistorical": QianjiEquityHistoricalFetcher,
        "EquitySearch": QianjiEquitySearchFetcher,
        "IncomeStatement": QianjiIncomeStatementFetcher,
        "BalanceSheet": QianjiBalanceSheetFetcher,
        "CashFlowStatement": QianjiCashFlowStatementFetcher,
        "HistoricalDividends": QianjiHistoricalDividendsFetcher,
    },
)
