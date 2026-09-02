# Choice 实时行情与 OpenBB 查询扩展说明（v0.10.0）

## 本版完成内容

- Choice Provider 新增 OpenBB `EquityQuote` Fetcher；
- 使用官方一次性快照接口 `csqsnapshot`，不建立持续订阅连接；
- 新增 SQLite `equity_quote_snapshot` 表和采集审计表；
- `qianji` Provider 新增从 SQLite 读取最新快照的 `EquityQuote` Fetcher；
- 新增 `11_Choice实时行情与OpenBB查询验收.ipynb`；
- 三证券快照在一次 Choice 请求中完成，重复落库不会产生重复记录。

## 安装顺序

1. 备份项目中的 `.env` 和 `data/qianji_market.db`。
2. 把补丁按原目录覆盖到项目根目录。
3. 在 VS Code 中选择原来的 `dm311` Notebook 内核。
4. 从头运行更新后的 `notebooks/00_openBB环境构建.ipynb`。
5. 确认 `qianji-data-mini=0.10.0`、`openbb-choice=0.2.0`，Choice 和 qianji 实时行情路由均通过。
6. 彻底重启 Notebook 内核。
7. 从头运行 `notebooks/11_Choice实时行情与OpenBB查询验收.ipynb`。

## 验收调用

Choice 直连一次性快照：

```python
from openbb import obb

direct = obb.equity.price.quote(
    symbol="000001.SZ,600519.SH,300750.SZ",
    provider="choice",
    use_cache=False,
)
```

快照落库后从公司库读取：

```python
stored = obb.equity.price.quote(
    symbol="000001.SZ,600519.SH,300750.SZ",
    source="choice",
    provider="qianji",
    use_cache=False,
)
```

## 字段与单位

| Choice 字段 | 标准字段 | 单位 |
|---|---|---|
| `TIME` | `quote_time` / `last_timestamp` | `Asia/Shanghai` |
| `PRECLOSE` | `prev_close` | CNY |
| `OPEN` | `open` | CNY |
| `HIGH` | `high` | CNY |
| `LOW` | `low` | CNY |
| `NOW` | `last_price` | CNY |
| `VOLUME` | `volume` | share |
| `AMOUNT` | `amount` | CNY |

首次真实运行后仍应把成交量、成交额与 Choice 终端同一时刻显示值抽样核对。如果账号返回的量额单位不同，可通过 `.env` 中的 `CHOICE_VOLUME_MULTIPLIER` 和 `CHOICE_AMOUNT_MULTIPLIER` 调整。

## 验收边界

- 本版是一次性实时快照，不是逐笔行情或长连接推送；
- 停牌、休市或无实时行情权限可能返回空值或明确错误；
- Notebook 默认三只样本证券，不能据此认定全市场实时行情权限已经开通；
- Notebook 会调用一次 Choice 实时行情接口，运行前应确认账号实时行情权限与流量。
