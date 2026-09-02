# Choice财务报表与分红正式集成（qianji-data-mini 0.8.1）

本补丁把09号Notebook已经真实验收通过的Choice官方`CTR`调用下沉到插件源码，形成“Choice → 标准事实模型 → SQLite → 审计记录”的正式采集链路。

## 已实现范围

- 默认3只证券：`000001.SZ`、`600519.SH`、`300750.SZ`；
- 默认2个报告期：`2025-12-31`、`2026-06-30`；
- 利润表：`IncomeStatementSHSZ`；
- 资产负债表：`BalanceStatementSHSZ`；
- 现金流量表：`CashFlowStatementSHSZ`；
- 分红实施：`DividendImplementationInfo`，按报告期口径`DateType=3`查询；
- 单项请求失败只写入错误审计，不丢弃其他证券、报告期和报表的成功结果；
- 财务请求一旦返回`10001029`，立即熔断剩余财务请求，避免额度耗尽后继续无效调用；
- 同一参数重复执行时按主键更新，不增加重复事实。

本期不做全A股财务全量下载，也暂未把财务与分红注册为OpenBB标准财务Fetcher。

## 请求结构

默认3只证券、2个报告期会产生21次有界请求：

- 三张财务报表：`3证券 × 2报告期 × 3报表 = 18`次；
- 分红实施：每只证券在完整报告期范围请求1次，共3次。

所有`CTR`请求都把`Ispandas=1`放在options末尾，并验证返回类型、字段和空表状态。

## SQLite表与粒度

| 表 | 主键粒度 | 说明 |
|---|---|---|
| `financial_statement_fact` | 来源+证券+报表类型+报告期+指标 | 三张财务报表长表事实 |
| `dividend_fact` | 来源+证券+报告期+指标 | 分红实施长表事实 |
| `financial_ingestion_run` | 运行ID | 请求范围、行数和错误审计 |

事实表同时保存`value_numeric`和`value_text`，原始CTR行保存在`raw_json`。带文字说明且无法安全转为数字的字段只保存文本，空值不写成0。

## 单位口径

- 财务报表字段：`CNY`；
- 税前/税后每股现金分红：`CNY/share`；
- 配股基数：`10k_share`；
- 分红日期字段：`date`；
- 分红方式：`text`；
- 送股/转增比例：`vendor_raw_ratio`，保留厂商原始尺度。

## 安装与运行

1. 将补丁内容覆盖到原`qianji_openbb_mini`项目根目录；
2. 运行`notebooks/00_openBB环境构建.ipynb`；
3. 确认`qianji-data-mini`版本为`0.8.1`；
4. 彻底重启Notebook内核；
5. 运行`notebooks/09_Choice财务报表与分红小样本验收.ipynb`。

也可以在终端运行：

```bash
qianji-data ingest-choice-financial \
  --symbols 000001.SZ,600519.SH,300750.SZ \
  --report-dates 2025-12-31,2026-06-30 \
  --report-type 1
```

Windows命令提示符中请写成一行。

## 验收标准

- Choice登录成功；
- 21次请求均有明确的成功、成功空表或错误记录；
- 三张报表覆盖全部样本证券和报告期；
- 事实表无重复主键；
- 重复运行后事实表总行数不增加；
- SQLite `quick_check`为`ok`；
- 单位、空值和日期格式符合上述口径。

用户最新真实验证结果为19项验收门槛全部通过、21次请求全部成功，说明该小样本链路可以进入插件源码阶段。
