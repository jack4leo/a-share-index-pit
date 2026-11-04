# A 股指数成分 PIT

一个可审计、可扩展的 A 股指数成分 point-in-time（PIT）采集参考实现。它将公开代码与个人数据分开：本仓库公开方法、代码、测试和数据模型；每日采集输出应写入用户自己的**私有**数据仓库，避免把未经授权的指数样本数据再分发到公开仓库。

## 先看结论

指数成分是带时间语义的事件数据，不是“今天的成分表”。回测至少要回答两个不同的问题：

- **有效时间**：该成分从哪个交易日/开盘或收盘边界起属于指数。
- **知悉时间**：公告何时发布、采集器何时首次看到，以及之后是否被修订。

项目同时保存公告/源文件时间与有效日期，并保留哈希、来源 URL、解析版本和采集状态。无法从源文件确认生效边界时，数据会明确标记为 `unknown` 或 `observed_state_only`，不会伪装成权威生效日。

## 当前实现范围

- 国证/深证（CNI）：依据官方目录可见标记发现候选指数，覆盖 399xxx、980xxx 和目录中的字母数字编码；读取官方样本文件。对已抽检的主流代码，该端点只返回一个带日期的当前快照；采集器据此与上一日状态差分，从首次运行起积累 ADD/REMOVE，不把每次快照伪装为历史回放。
- 中证、上证、深证、北证：从中证官网指数浏览器的 CSI/SSE/SZSE/BSE 官方目录发现境内股票指数，并读取中证官网当前成分清单。该来源从首次采集日起积累快照，不代表能免费回溯所有历史日期。
- 东方财富仅作可选的二级当前快照 fallback；其结果会标记为 `secondary`，不能替代指数编制方公告或授权数据。

“全部 A 股指数”是一个持续发现和核对的范围，不是单一 API 能保证的属性。目录可能包含债券、境外或混合资产指数；采集器会按成分证券代码识别 A 股股票样本，并记录 `in_scope`、`partial`、`out_of_scope`、`missing` 等状态。新指数或新来源必须显式进入覆盖清单。免费网页/API 不足以保证所有指数、所有临时调整、权重、公司行为和所有历史日期完整。

## 快速开始

```bash
python -m pip install -r requirements.txt
python scripts/collect.py --data-dir ./data --limit 5 --dry-run
```

移除 `--limit 5 --dry-run` 才会写入数据文件。私有仓库示例工作流位于 [`private-data-template/.github/workflows/daily.yml`](private-data-template/.github/workflows/daily.yml)，每天北京时间 16:30 触发（GitHub cron 使用 UTC）。周末和节假日若来源状态不变，只增加观测，不生成虚假的成员变更。工作流以完整 commit SHA 固定公开采集器；采集作业没有仓库内容权限，只有独立提交作业获得 `contents: write`，避免公开代码接触写凭据。

## 数据模型

- `data/index_catalog.csv`：发现到的指数代码、名称、编制方/目录来源、候选范围，以及原生分类和规范化分类标签。
- `data/catalog_errors.csv`：目录来源不可用或目录发现失败时的来源级错误。
- `data/collection_runs.csv`：每次运行的成功/失败计数、目录完整性和运行状态。
- `data/observations.csv`：每次按指数的观测、来源日期、数量、状态与 SHA-256。
- `data/membership_events.csv`：首次基线、纳入和剔除事件；区间可由事件按有效日期还原。
- `data/latest_state.json`：用于下一次差分的当前状态，不覆盖事件账本。
- `data/source_history/`：按指数保存可得的历史样本标准化版本；私有数据仓库的 Git 历史保留版本变化。

目录来源有故障时，采集器保留并使用上次完整目录中对应来源的候选项，不用不完整结果覆盖 `index_catalog.csv`。若来源快照日期倒退，观测记录会标记为 `stale_snapshot` 并保留其 `source_asof` 与 `observed_at`，但不会回退最新状态或生成事件。所有指数抓取失败时，诊断先写入数据文件，工作流会提交诊断后再以失败状态结束。

列定义与查询约定见 [`docs/data-model.md`](docs/data-model.md)。调研结论和来源见 [`docs/research.md`](docs/research.md)。

## 重要限制

中证规则允许指数方法学覆盖通用样本调整规则；定期调整、临时调整、公告日和生效日都必须分别处理。中证 A500 与中证1000的方案要求半年调整，但临时事件也会改变样本。对多个国证代码，官方“历史调样”下载端点实测返回“文件不存在”；样本文件也只给最新状态，因此国证的可信 PIT 起点是首次每日采集，历史缺口仍在。国证公开网站列明样本股清单、权重、公司行为和调整名单属于数据服务产品；CIIS 说明中证机构级成分、权重、公司事件与除数需要牌照许可。因此公开代码不等于公开数据授权。参见[国证数据产品说明](https://www.cnindex.com.cn/zh_services/index_agent/index.html?act_menu=4&act_service=4)和[CIIS 产品说明](https://www.ciis.com.hk/hongkong/sc/idata/csifundamentaldata/index.shtml)。

本项目不是投资建议，也不承诺数据完整性或交易级 SLA。正式回测前应以有授权的数据产品和编制方公告交叉校验。
