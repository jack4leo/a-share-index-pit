# A 股指数 PIT 私有数据仓库

此目录用于初始化私有 GitHub 仓库 `a-share-index-pit-data`。将本目录内容复制到该私有仓库根目录后，Actions 会每天北京时间 16:30（周一至周日）运行采集器，并把观测日志和成员事件提交回**本私有仓库**。周末/节假日若来源状态未变，只会增加观测记录，不产生成员变更事件。

## 凭据与执行隔离

工作流分为三个作业：只读准备作业导出已有 `data/` 状态；无仓库内容权限的采集作业运行公开采集器；单独的提交作业才获得 `contents: write`。采集器以完整 Git commit SHA 固定，并且不会在持有写权限的作业中执行。更新采集器版本时，应审查新代码并只修改工作流里的 `COLLECTOR_COMMIT` 为完整 SHA，再手动运行一次验证。

## 数据与诊断

国证指数服务说明将样本股清单、权重、公司行为和调整名单列为数据服务产品；CIIS 的 CSI 日度成分/权重产品需要牌照许可。请勿将 `data/` 推到公共仓库，也请先确认个人使用和存储符合相应来源条款。若要对外发布数据，须先取得相应许可。

首次手动运行建议用 `workflow_dispatch`，输入 `limit=5` 做 smoke test；检查 `data/observations.csv` 的 `source_status`、`source_asof` 与覆盖情况。留空 `limit` 后才会处理全部发现到的候选指数。目录不可用时会写入 `data/catalog_errors.csv`；每次运行状态和目录完整性写入 `data/collection_runs.csv`；逐指数失败原因保存在 `data/observations.csv`，工作流失败日志也会进入 `data/diagnostics/`。即使全量抓取失败，工作流也会先提交这些诊断，再以失败状态结束。
