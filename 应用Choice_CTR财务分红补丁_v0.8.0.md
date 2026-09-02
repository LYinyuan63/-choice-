# 应用Choice CTR财务分红补丁 v0.8.0

## 覆盖前

1. 关闭正在运行的Notebook内核；
2. 备份本地`.env`和`data/qianji_market.db`；
3. 不要用补丁中的`.env.example`覆盖自己的`.env`。

## 覆盖与安装

1. 将压缩包解压到`qianji_openbb_mini`项目根目录，允许覆盖同名源码；
2. 打开并从上到下运行`notebooks/00_openBB环境构建.ipynb`；
3. 确认输出中的`qianji-data-mini`版本为`0.8.0`；
4. 彻底重启VS Code和Notebook内核。

## 验收

先运行：

```text
notebooks/09_Choice财务报表与分红小样本验收.ipynb
```

通过后可执行：

```text
clients/运行Choice财务分红落库.py
```

或者运行命令：

```bash
qianji-data ingest-choice-financial --symbols 000001.SZ,600519.SH,300750.SZ --report-dates 2025-12-31,2026-06-30 --report-type 1
```

## 本补丁不会改动

- 不包含也不会覆盖`.env`；
- 不包含也不会覆盖`qianji_market.db`；
- 不会自动全A股下载；
- 不会强制登录或打印Choice账号、密码、Token；
- 不会把财务接口虚假注册成已经完成的OpenBB Fetcher。
