# Choice证券主数据OpenBB查询扩展（qianji-data-mini 0.5.0）

本补丁新增公司库证券搜索能力，将SQLite `security_master`注册为OpenBB
`EquitySearch` Fetcher。

## 数据链路

```text
Choice采集 → SQLite security_master → OpenBB provider="qianji"
```

OpenBB查询只读取本地SQLite，不会重新登录Choice，也不会消耗Choice调用额度。

## 覆盖方法

1. 关闭正在运行的Notebook内核；
2. 将补丁压缩包内容覆盖到`qianji_openbb_mini`项目根目录；
3. 打开`notebooks/00_openBB环境构建.ipynb`并全部运行；
4. 确认`qianji-data-mini`版本为`0.5.0`，且`openbb-build`成功；
5. 彻底重启Notebook内核；
6. 运行`notebooks/07_Choice证券主数据_OpenBB查询验收.ipynb`。

不能只复制07号Notebook：旧版0.4.0尚未注册`EquitySearch`，必须同时覆盖本补丁。

## OpenBB调用示例

```python
from openbb import obb

result = obb.equity.search(
    query="平安银行",
    provider="qianji",
    source="choice",
)
result.to_dataframe()
```

## 本次验证

- 自动化测试：28项通过；
- OpenBB代码查询：`000001.SZ`返回`平安银行`；
- OpenBB中文名称查询：`平安银行`返回`000001.SZ`；
- 模糊查询：`银行`返回38条；
- 全部在市A股：OpenBB返回5212条，与上传SQLite一致；
- 全量重复代码、关键字段缺失、来源异常、交易所映射异常均为0；
- 07号质量门槛：20项通过，0项失败。

以上数量对应2026-08-31的用户验证数据库快照，后续会随证券上市、退市和数据更新变化。
