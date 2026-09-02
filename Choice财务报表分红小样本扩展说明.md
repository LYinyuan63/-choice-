# Choice财务报表与分红小样本扩展（qianji-data-mini 0.7.0）

本补丁在0.6.0参考数据基础上增加Choice财务报表和分红小样本验证链路。

## 本期边界

- 默认3只证券：`000001.SZ`、`600519.SH`、`300750.SZ`；
- 默认2个报告期：`2025-12-31`、`2026-06-30`；
- 覆盖利润表、资产负债表、现金流量表和分红候选指标；
- 不进行全A股批量下载；
- 不在未知口径下换算金额和比例。

Choice官方说明中，`css`用于基本资料、财务、估值等截面数据；`ReportDate`是季度最后一个自然日，而不是实际公告披露日。指标详情和特有参数仍应以Choice命令生成器为准：

- https://quantapi.eastmoney.com/Upload/EMQuantAPI_Python.html
- https://quantapi.eastmoney.com/Cmd/ChoiceSerialSection?from=web

## 指标探测

Notebook先用一个样本证券和最近报告期逐项调用候选指标。成功返回且结构可解析的指标进入正式下载；失败指标保存错误码和错误信息。

被拒指标不自动算项目失败，只要每个数据集仍有至少一个有效指标。若某类候选指标全部被拒，需要从Choice命令生成器复制当前账号可用的英文指标简称，填入`.env`：

```text
CHOICE_INCOME_INDICATORS=...
CHOICE_BALANCE_INDICATORS=...
CHOICE_CASHFLOW_INDICATORS=...
CHOICE_DIVIDEND_INDICATORS=...
```

## 新增SQLite表

| 表 | 粒度 | 说明 |
|---|---|---|
| `financial_statement_fact` | 来源+证券+报表类型+报告期+指标 | 三张财务报表长表事实 |
| `dividend_fact` | 来源+证券+报告期+指标 | 分红方案、金额和日期类长表事实 |
| `financial_ingestion_run` | 运行ID | 指标探测、下载数量和错误审计 |

事实表同时保存`value_numeric`和`value_text`。日期、方案说明等保存在文本字段；能安全转换的数值同时写入数值字段。原始返回保存在`raw_json`。

所有金额、比例和日期类指标在确认具体Choice指标单位前统一标记：

```text
unit=vendor_raw
```

这不是正式标准单位，而是防止把“万元”误写为“元”、把百分数误写为小数。

## 安装顺序

1. 关闭Notebook内核；
2. 将0.7.0补丁覆盖到原`qianji_openbb_mini`项目根目录；
3. 运行`notebooks/00_openBB环境构建.ipynb`；
4. 确认`qianji-data-mini`版本为`0.7.0`；
5. 彻底重启内核；
6. 运行`notebooks/09_Choice财务报表与分红小样本验收.ipynb`。

不能只复制09号Notebook，旧版本没有新增事实表和财务编排函数。

## 验收规则

- 每类数据至少一个指标通过探测；
- 正式请求没有错误；
- 覆盖全部样本证券、报告期和三张报表；
- 财务及分红至少存在一个非空值；
- 事实表无重复主键；
- 同一参数运行两次，事实表行数不增加；
- SQLite完整性检查通过；
- 单位保持`vendor_raw`，等待人工核对。

本补丁模拟Choice端到端Notebook验证为20项全部通过；完整自动化测试为31项全部通过。
