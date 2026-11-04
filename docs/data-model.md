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

只有官方目录发现完整时才更新候选清单。若任一目录来源不可用，`index_catalog.csv` 保持上次完整版本；采集器会将该来源上次的候选项与本次可用来源的结果合并后继续抓取。`candidate_scope` 初始为 `candidate_pending_sample_validation`，不代表已经完整确认属于 A 股权益指数。

目录同时保存发布方原生分类和规范化的多维分类：

- `source_classification`：JSON 对象，原样保留目录分类字段。CNI 保存 `indextype` 代码及官网类型标签；CSI 保存 `indexClassify`、`assetsClassify`、`region` 等可用原生字段。规范化不会覆盖或替代原值。
- `primary_category`：单一规范主类别，可能值包括 `market_size`、`sector_industry`、`style_factor`、`thematic`、`strategy`、`composite`、`fixed_income`、`fund`、`customized`、`currency`、`cross_border`、`multi_asset`、`other` 和 `unknown`。
- `universe_scope_tags`、`geography_region_tags`、`style_factor_tags`、`strategy_tags`：独立维度的 JSON 字符串数组，不与主类别互斥。例如一个风格指数可以同时有 `primary_category=style_factor`、`universe_scope_tags=["equity"]` 和 `style_factor_tags=["style"]`。`unknown` 表示来源缺少或暂不支持该维度；空数组表示没有可附加的风格/策略标签。

CSI 的主类别映射依据官方目录 `indexClassify`：规模→`market_size`、行业→`sector_industry`、风格→`style_factor`、主题→`thematic`、策略→`strategy`、综合→`composite`；信用债、利率债和可转债归为 `fixed_income`。`assetsClassify` 用于 universe/scope 标签，`region` 用于地域标签（如境内→`china_mainland`、沪深港→`china_mainland_hong_kong`）。

CNI 使用官网指数系列菜单的 `indextype` 类型码：100/200 规模、101/201 行业、102/202 风格、103/203 主题、104/204 策略、105/205 综合、106/206 债券、107/207 基金、108/208 定制、111/211 多资产、199/299 其他；209 人民币指数映射为 `currency`，210 跨境指数映射为 `cross_border`。前述股票分类只生成宽泛的 `equity` universe 标签，不声称一定是 A 股；210 只标记跨境地域，不推断其资产类别。其他发布方系列类型或未来新增代码保留在 `source_classification` 中，并将 `primary_category` 设为 `unknown`，不根据指数名称猜测。类型名称依据[国证官网指数系列](https://www.cnindex.com.cn/module/index-series.html?act_menu=1&index_type=-1)的官方菜单；CSI 原生字段来自[中证官网指数浏览器](https://www.csindex.com.cn/zh-CN/indices/family/list)。

### `observations.csv`

按 `run_id + provider + index_code` 记录一次采集结果。状态包括 `ok`、`ok_secondary`、`fetch_failed`、`empty_source`、`partial_non_a_members`、`stale_snapshot` 等。发生来源日期回退时，仍保留该快照的 `source_asof` 和本次 `observed_at`，但不更新最新状态或产生事件。错误和空结果始终与“没有成分变化”区分开。

### `catalog_errors.csv`

逐次追加目录发现失败记录，包括 `observed_at`、`run_id`、失败的目录来源、状态和具体错误消息。它与逐指数的 `observations.csv` 分开，便于区分目录不可用和成分文件抓取失败。

### `collection_runs.csv`

逐次记录运行级索引数、成功/失败数、目录是否完整、运行状态和简短摘要。即使没有发现候选，或所有指数抓取失败，也会先持久化这条记录再让进程以失败状态退出。

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
