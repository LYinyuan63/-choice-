"""Register Choice fetchers with OpenBB Platform."""

from openbb_core.provider.abstract.provider import Provider

from openbb_choice.models.equity_historical import ChoiceEquityHistoricalFetcher
from openbb_choice.models.equity_quote import ChoiceEquityQuoteFetcher


provider = Provider(
    name="choice",
    description="Eastmoney Choice EmQuantAPI data provider for OpenBB.",
    website="https://quantapi.eastmoney.com/",
    credentials=["username", "password"],
    instructions=(
        "Install the official EmQuantAPI Python SDK on the same machine, then set "
        "choice_username and choice_password in OpenBB user credentials."
    ),
    fetcher_dict={
        "EquityHistorical": ChoiceEquityHistoricalFetcher,
        "EquityQuote": ChoiceEquityQuoteFetcher,
    },
)
