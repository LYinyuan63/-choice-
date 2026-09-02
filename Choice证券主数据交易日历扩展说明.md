# Choice证券主数据与交易日历扩展（qianji-data-mini 0.4.0）

本扩展新增Choice证券主数据、沪深交易日历及06号真实落库验收Notebook。

## 新增能力

- Choice `css`证券主数据调用；
- Choice `sector("001004", 日期)`全部A股代码入口；
- Choice `tradedates`沪深交易日调用；
- SQLite `security_master`表；
- SQLite `trading_calendar`表；
- SQLite `reference_ingestion_run`运行记录表；
- 两类数据幂等写入和统一Python查询；
- 06号Excel、JSON及数据地图证据导出。

## 安装顺序

1. 将扩展压缩包解压到现有`qianji_openbb_mini`项目根目录，允许覆盖同名代码文件。
2. 本扩展不包含`.env`和数据库，不会覆盖现有账号配置及`data/qianji_market.db`。
3. 打开`notebooks/00_openBB环境构建.ipynb`，选择`dm311`内核并从头运行。
4. 00号全部通过后，彻底重启Notebook内核。
5. 打开`notebooks/06_Choice证券主数据与交易日历落库验收.ipynb`并从头运行。

06号应显示：

```text
qianji-data-mini版本：0.4.0
EmQuantAPI：导入成功
主数据范围：sample
```

默认只取3只样本证券和沪深约两个月日历，并连续执行两次验证幂等。第一次不要切换到`all_a`。

样本验收通过、并确认Choice合同允许批量下载和本地保存后，才将：

```python
MASTER_SCOPE = "sample"
```

改为：

```python
MASTER_SCOPE = "all_a"
```

全部A股板块代码默认使用Choice官方`001004`。证券主数据可选指标若无权限，代码会从`NAME,LISTDATE,DELISTDATE`降级到`NAME,LISTDATE`或`NAME`，并在验收结果中记录上市/退市日期缺失情况。
