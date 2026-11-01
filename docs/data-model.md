# 数据模型与查询约定

## 时间字段

- `effective_date`：源文件标注的样本状态日期。对 CSI/CNI 当前成分文件和二级快照，如果源没有声明真正生效边界，该字段仅是源状态日期，不自动等同于开盘/收盘生效时点。
- `valid_boundary`：`source_date`、`open`、`close` 或 `unknown`。首版不会推断未写在源文件中的边界。
- `announced_at`：公告首次发布的时间。当前快照 API 通常没有这个字段，所以不编造；公告解析器后续可以补充。
- `observed_at`：本采集器首次获取这份状态的 UTC 时间。
- `source_sha256`：下载响应字节的 SHA-256；用于判断同一来源文件是否变更。
- `membership_hash` / `state_hash`：排序后成分代码集合的 SHA-256；用于识别样本成员变化。
- `confidence`：包括 `official_file_state`、`official_current_state`、`official_dated_states`、`history_start_unverified`、`secondary_observed_state` 和 `same_date_source_correction_review_required`。官方当前状态仍不等于已确认公告生效日。

## 输出文件

### `index_catalog.csv`

每次运行从来源目录更新候选清单。`candidate_scope` 初始为 `candidate_pending_sample_validation`，不代表已经完整确认属于 A 股权益指数。

### `observations.csv`

按 `run_id + provider + index_code` 记录一次采集结果。状态包括 `ok`、`ok_secondary`、`fetch_failed`、`empty_source`、`partial_non_a_members`、`stale_snapshot` 等。错误和空结果始终与“没有成分变化”区分开。

### `membership_events.csv`

- `BASELINE`：首次观测到该指数的成员集合；只有从这次采集起才有观测证据，不应理解为更早历史的完整成员。
- `ADD` / `REMOVE`：在后续样本状态中观察到的成员差分。CNI 当前快照与 CSI 当前文件均和 `latest_state.json` 做跨日差分；首次运行只写 `BASELINE`，不会把每日当前表逐日误写成完整历史。
- `effective_date`：对应源文件日期；如果来源只给当前快照，可能是观察状态日期而非明确公告生效日。查询可观察状态时可用该日期；需要官方生效边界的研究必须结合公告校验 `valid_boundary` 与 `confidence`。
- `revision_of`：同一有效日期状态改变时的复核提示。此类记录需要人工核对原公告，不应静默当成已确认修订。

对某指数和日期 `D` 还原状态：取 `effective_date <= D` 的事件；从最早 `BASELINE` 开始，按日期应用 `ADD` / `REMOVE`。若要模拟“当时能知道什么”，还需将 `observed_at <= cutoff` 作为第二个时间条件。若源文件后来被修订，按 `observed_at` 选择当时版本，并利用 source hash 和私有仓库提交历史做审计。

## 证券代码

首版使用源证券代码，不把代码声明为永久 ID。代码校验只用于排除明显的债券、基金、B 股、境外股票和非股票指数样本；证券代码前缀规则可能随交易所制度变化，必须监控新增代码段。已核实的中航成飞代码变更（300114→302132）作为精确例外处理，不将整个 302 前缀推定为 A 股代码。生产回测应结合有许可的证券主数据，将代码、市场和证券生命周期映射到稳定证券 ID。

## 一致性检查

每次发布应检查：同一快照是否存在重复证券；有效日期是否缺失；源日期是否倒退；样本是否包含非 A 股证券；成分数是否异常；同一指数的成员 hash 是否变化；源目录新发现的指数是否进入 `missing` / `unsupported` 清单。权重完整性检查只有在相应指数方案和源字段明确时才运行，不能用简单合计 100% 替代指数权重规则。
