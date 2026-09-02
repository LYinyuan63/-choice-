# Choice 财务与分红 OpenBB 离线查询扩展说明（v0.9.0）

## 本版完成内容

本版在公司数据 Provider `qianji` 中新增四条 OpenBB 标准查询接口。接口只读取 `data/qianji_market.db` 中已经落库的 Choice 数据，不导入 EmQuantAPI、不登录 Choice、不调用 CTR，也不消耗 Choice 流量。

| 数据集 | OpenBB 调用 | SQLite 来源 |
|---|---|---|
| 利润表 | `obb.equity.fundamental.income(..., provider="qianji")` | `financial_statement_fact` 的 `income` 事实 |
| 资产负债表 | `obb.equity.fundamental.balance(..., provider="qianji")` | `financial_statement_fact` 的 `balance` 事实 |
| 现金流量表 | `obb.equity.fundamental.cash(..., provider="qianji")` | `financial_statement_fact` 的 `cashflow` 事实 |
| 历史现金分红 | `obb.equity.fundamental.dividends(..., provider="qianji")` | `dividend_fact` |

财务事实会按“证券代码 + 报告期”从长表转为 OpenBB 宽表。分红标准接口要求同时存在除权日 `DIVEXDATE` 和税前每股现金分红 `DIVCASHPSBFTAX`；不满足这一条件的送股、转增或未实施方案仍保留在 SQLite 原始事实表中，但不会伪装成标准现金分红事件。

## 安装与构建

1. 备份项目中的 `.env` 和 `data/qianji_market.db`。
2. 把补丁文件按原目录覆盖到项目根目录。
3. 在 VS Code 中选择原来的 `dm311` Notebook 内核。
4. 从头运行 `notebooks/00_openBB环境构建.ipynb`。
5. 确认 `qianji-data-mini` 版本为 `0.9.0`，且“qianji财务分红路由完整”为 `PASS`。
6. 彻底重启 Notebook 内核。
7. 从头运行 `notebooks/10_Choice财务分红_OpenBB查询验收.ipynb`。

## Python 调用示例

```python
from openbb import obb

income = obb.equity.fundamental.income(
    symbol="000001.SZ",
    start_date="2025-01-01",
    end_date="2026-12-31",
    source="choice",
    provider="qianji",
    use_cache=False,
)
display(income.to_dataframe())

dividends = obb.equity.fundamental.dividends(
    symbol="000001.SZ",
    start_date="2020-01-01",
    end_date="2026-12-31",
    source="choice",
    provider="qianji",
    use_cache=False,
)
display(dividends.to_dataframe())
```

## 命令行验收

在项目根目录执行：

```powershell
& D:\minicoda3\envs\dm311\python.exe clients\查询Choice财务分红_OpenBB.py
```

脚本会查询三只样本证券并把结果导出到 `outputs`，同时检查查询过程没有新增落库运行记录。

## 验收边界

- 本版验收的是“已落库数据能够通过 OpenBB 标准接口读取”，不是重新从 Choice 下载。
- OpenBB 标准字段仅映射本期已验收的 10 个财务指标；SQLite 中其他 Choice 指标不丢失。
- 查询没有数据时，OpenBB 会返回空数据错误；这通常表示该证券、报告期或分红事件尚未落库，不代表 Provider 登录失败。
- 财务金额统一按数据库中的 `CNY` 口径输出；现金分红金额为 `CNY/share`。
