# A 股指数 PIT 私有数据仓库

此目录用于初始化私有 GitHub 仓库 `a-share-index-pit-data`。将本目录内容复制到该私有仓库根目录后，Actions 会每天北京时间 16:30（周一至周五）运行公开采集器，将观测日志和成员事件提交回**本私有仓库**。

该结构有意将可复用代码与指数样本数据分开。国证指数服务说明将样本股清单、权重、公司行为和调整名单列为数据服务产品；CIIS 的 CSI 日度成分/权重产品需要牌照许可。请勿将 `data/` 推到公共仓库，也请先确认个人使用和存储符合相应来源条款。若需要对外发布数据，须先取得相应许可。

首次手动运行建议用 `workflow_dispatch`，输入 `limit=5` 做 smoke test；检查 `data/observations.csv` 的 source status、source date 与 coverage。留空 limit 后才会处理全部发现到的候选指数。来源不可用、非股票/混合样本和 API 抓取失败均会作为独立状态记录。

工作流通过 `GITHUB_TOKEN` 只写入这个数据仓库，不需要另行添加 PAT 或将凭据放在公开代码仓库。默认使用 `contents: write` 权限，以便提交每日更新。
