# openbb-choice

Choice EmQuantAPI data provider extension for OpenBB Platform. Its package and Fetcher layout follows the same OpenBB provider mechanism used by `openbb-tushare` and `openbb-akshare`.

## Current P0 coverage

| OpenBB Fetcher | Python call | HTTP route | Status |
|---|---|---|---|
| `EquityHistorical` | `obb.equity.price.historical(..., provider="choice")` | `GET /api/v1/equity/price/historical?provider=choice` | Implemented; real-account verification required |
| `EquityQuote` | `obb.equity.price.quote(..., provider="choice")` | `GET /api/v1/equity/price/quote?provider=choice` | One-shot `csqsnapshot`; real-account verification required |

The extension does not register profile, search, or financial-statement Fetchers. Company-database search and financial queries are provided by the separate `qianji` Provider.

## Prerequisites

1. Windows machine with the official Choice EmQuantAPI Python SDK.
2. Choice account with QuantAPI permission.
3. OpenBB Platform 4.7.1 or later.
4. The EmQuantAPI SDK and OpenBB extension must be installed into the same virtual environment.

`EmQuantAPI` is not a PyPI dependency. Download its official package separately and run `installEmQuantAPI.py` with the virtual environment's Python.

## Install

From this directory:

```powershell
python -m pip install -e .
openbb-build
```

Restart Python or the Jupyter kernel after rebuilding OpenBB.

From the parent MVP project, a beginner-friendly alternative is to double-click
`安装Choice_OpenBB插件.bat` and restart VS Code afterwards. Then run
`clients/验证Choice_OpenBB插件.py` for the real-account acceptance test.

## Credentials

OpenBB prefixes provider credentials with the provider name. For the current Python session:

```python
from openbb import obb

obb.user.credentials.choice_username = "YOUR_USERNAME"
obb.user.credentials.choice_password = "YOUR_PASSWORD"
```

For persistent local configuration, place the following keys under `credentials` in `~/.openbb_platform/user_settings.json`:

```json
{
  "credentials": {
    "choice_username": "YOUR_USERNAME",
    "choice_password": "YOUR_PASSWORD"
  }
}
```

Do not commit or share that file. The provider does not print the login options or include credentials in its results.

If the machine has already been activated with the official `LoginActivator` and a valid `userInfo`, direct Fetcher testing can use `CHOICE_LOGIN_MODE=userinfo`. The standard OpenBB Provider registration still declares username and password so the REST/Python application can validate credentials consistently.

## Python verification

```python
from openbb import obb

result = obb.equity.price.historical(
    symbol="000001.SZ",
    start_date="2026-08-01",
    end_date="2026-08-31",
    period="daily",
    use_cache=False,
    provider="choice",
)

print(result.provider)
print(result.results[:3])
```

One-shot quote snapshot:

```python
quote = obb.equity.price.quote(
    symbol="000001.SZ,600519.SH",
    use_cache=False,
    provider="choice",
)
print(quote.to_dataframe())
```

Expected provider value:

```text
choice
```

## HTTP verification

After starting OpenBB's FastAPI service, the standard route is:

```text
GET /api/v1/equity/price/historical
```

Example query parameters:

```text
provider=choice
symbol=000001.SZ
start_date=2026-08-01
end_date=2026-08-31
period=daily
use_cache=false
```

This matches the standard route used by the reference Tushare and AKShare providers; only the `provider` value changes.

## Data conventions

- Symbols: `000001.SZ`, `601988.SH`, `430047.BJ`, `00700.HK`.
- `Period`: Choice `1/2/3` maps to `daily/weekly/monthly`.
- `AdjustFlag`: Choice `1/2/3` maps to unadjusted/`hfq`/`qfq`.
- `change_percent`: converted from percentage points to a normalized decimal. `1.25` from Choice becomes `0.0125` in OpenBB.
- Weekly/monthly rows whose four OHLC values are all empty are treated as unfinished-period placeholders: they are skipped with a structured warning. A partly empty OHLC row raises an explicit source-data error.
- Volume unit: configured as shares; verify the account's actual return against the Choice terminal before changing `CHOICE_VOLUME_MULTIPLIER`.
- Amount unit: configured as CNY; verify before changing `CHOICE_AMOUNT_MULTIPLIER`.
- `ForceLogin=1` is blocked unless `CHOICE_ALLOW_FORCE_LOGIN=1` is explicitly set.
- Real-time quotes use `csqsnapshot`, not the streaming `csq` subscription. This keeps each acceptance run bounded to one request.

## Development tests

Tests use a fake EmQuantAPI object and never require real credentials:

```powershell
python -m pip install -e ".[dev]" --no-deps
python -m pytest -q
```

Real-account acceptance is a separate step and must run on the authorized Windows machine.
