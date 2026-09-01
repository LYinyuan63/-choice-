# Choice 月线修复补丁（openbb-choice 0.1.2）

本补丁修复 05 号验收中 Choice 月线返回全空 OHLC 占位记录时，OpenBB 整批校验失败的问题。

## 修复边界

- `OPEN/HIGH/LOW/CLOSE` 四项全部为空：视为未完成周期占位记录，跳过并产生带证券、日期、周期的警告证据。
- OHLC 只有部分字段为空：仍抛出明确错误，不把真实坏数据静默过滤。
- 05 号 Notebook 新增“月线空占位”工作表和 JSON 字段 `skipped_empty_placeholders`。
- 不修改 `.env`、Choice 激活文件和 SQLite 数据库。

## 安装

把补丁压缩包解压到现有 `qianji_openbb_mini` 项目根目录，并允许覆盖同名文件。

在 VS Code 的 Notebook 中选择平时使用的 `dm311` 内核，运行：

```python
import subprocess
import sys
from pathlib import Path

项目根目录 = Path(r"D:\OneDrive\桌面\qianji_openbb_mini")  # 改成你的实际路径

subprocess.run(
    [sys.executable, "-m", "pip", "install", "-e", str(项目根目录 / "extensions" / "openbb_choice")],
    check=True,
)
subprocess.run(
    [sys.executable, "-c", "import openbb; openbb.build()"],
    check=True,
)
print("安装和 OpenBB 构建完成，请彻底重启 Notebook 内核。")
```

彻底重启内核后，从头运行 `notebooks/05_Choice多证券与多周期增量验收.ipynb`。

环境检查应显示：

```text
openbb-choice版本： 0.1.2
OpenBB发现choice： True
OpenBB发现qianji： True
```

最终 Excel 中应新增“月线空占位”工作表。该表有记录并不代表失败；它证明占位记录已被隔离。正式的日、周、月结果中 OHLC 缺失数必须为 0。
