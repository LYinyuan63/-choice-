# 千际轻量四源数据基座 MVP

需要用现有 Tushare Token 和 Choice 账号自动取得真实验证数据时，请先看
`真实数据自动验证说明.md`，然后运行 `运行真实数据验证.bat`。

按照 `openbb-tushare` 和 `openbb-akshare` 的 Provider/Fetcher 结构开发的
独立 Choice OpenBB 扩展位于 `extensions/openbb_choice`。该扩展目前只注册
已经实现的 `EquityHistorical`，不会把未完成接口标记为可用。

这是一个适合在 Windows + VS Code/Jupyter 上先跑通的小型项目，完成以下闭环：

1. 从 Wind、Choice、iFinD、Tushare 或内置模拟源获取日线行情；
2. 把字段统一为同一套 OHLCV 结构；
3. 保存到本机 SQLite 数据库；
4. 通过 Python、REST、Excel 和 OpenBB `provider="qianji"` 消费；
5. 在没有商业接口权限时，用 `mock` 模拟源完整验收流程。

> 本版本只做“选定证券 + 指定日期范围的日线行情”。它不是四个平台的全量下载器，也不包含新闻、研报、财务报表和实时推送。

## 最简单的运行方法

打开 `notebooks/01_本地小型数据基座演示.ipynb`，从上到下运行。Notebook 会安装项目、生成模拟行情、落入 SQLite、调用模拟客户端并导出 Excel。

## 四个真实数据源的前置条件

| 数据源 | 本项目接入方式 | 电脑需要准备 |
|---|---|---|
| Tushare | 官方 Python 包 | `.env` 中填写 `TUSHARE_TOKEN`，账号具备相应积分权限 |
| iFinD | 官方 QuantAPI HTTP | `.env` 中填写 `IFIND_REFRESH_TOKEN`，账号开通接口权限与网络白名单 |
| Wind | `WindPy` 本地 SDK | 安装 Wind 金融终端及 Python 插件，并在本机成功登录 |
| Choice | `EmQuantAPI` 本地 SDK | 安装 Choice 量化接口包并完成账号/令牌激活 |

商业终端能查看数据，不代表合同一定允许批量下载、本地长期存储或公司内部再分发。正式使用前需要由账号负责人确认权限范围。

## 常用命令

这些命令也全部写进了 Notebook，不熟悉终端可以不单独执行。

```bash
qianji-data init-db
qianji-data ingest --source mock --symbols 000001.SZ,600000.SH --start 2026-08-01 --end 2026-08-31
qianji-data query --symbol 000001.SZ --source auto
qianji-data export-excel --symbol 000001.SZ --output output.xlsx
qianji-data serve
```

本地服务启动后：

- 健康检查：`http://127.0.0.1:8765/health`
- Swagger：`http://127.0.0.1:8765/docs`
- 行情接口：`GET /v1/equity/price/historical`

## 接入 OpenBB

安装 OpenBB 可选依赖后，需要重启 Jupyter 内核并执行一次 `openbb-build`：

```python
%pip install -e ".[openbb]"
!openbb-build
```

重启内核后：

```python
from openbb import obb

result = obb.equity.price.historical(
    symbol="000001.SZ",
    start_date="2026-08-01",
    end_date="2026-08-31",
    provider="qianji",
    source="auto",
)
result.to_dataframe()
```

OpenBB 在这里是统一消费和路由层，SQLite 才是这个小型版本的实际存储层。

## 文件说明

- `src/qianji_data_mini/adapters/`：四源适配器和模拟适配器；
- `src/qianji_data_mini/db.py`：SQLite 表结构、幂等写入、统一查询；
- `src/qianji_data_mini/service.py`：本地 REST 服务；
- `src/qianji_data_mini/openbb_provider/`：OpenBB 私有 Provider；
- `clients/`：Python、REST、Excel、OpenBB 四种调用示例；
- `clients/check_environment.py`：只读检查各 SDK、Token 和数据库是否就绪；
- `tests/test_e2e.py`：无需商业账号即可运行的端到端测试。

## 已知边界

- Wind、Choice 的 Python 模块来自官方客户端安装包，不能通过普通 `pip` 完整替代；
- 四家厂商的指标代码、复权口径、成交量/成交额单位会随产品版本和购买权限变化；
- 本项目把 Tushare 日线 `vol` 从“手”乘以 100 转为“股”，把 `amount` 从“千元”乘以 1000 转为“元”；
- 其他三源的量额倍率可在 `.env` 调整，首次接入必须抽样核对；
- 默认 REST 只监听 `127.0.0.1`；没有设置 API Key 时不要直接暴露到公网。

## 官方资料

- OpenBB：<https://docs.openbb.co/>
- Tushare：<https://tushare.pro/document/2?doc_id=27>
- iFinD QuantAPI：<https://quantapi.51ifind.com/>
- Choice 量化接口：<https://quantapi.eastmoney.com/>
- Wind 金融终端 API：<https://www.wind.com.cn/mobile/WFT/en.html>
