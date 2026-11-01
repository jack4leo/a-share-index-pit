# 调研发现与来源

## 为什么 PIT 不能只存“目前成分”

供应商与指数公司把历史成分作为事件与状态序列处理。LSEG 的示例从一个日期的初始成分开始，再按逐日 joiner/leaver 事件更新状态；MSCI 的事件历史还区分已确认、预期、实施和更正等状态。对回测而言，至少需要分别保存有效日、公告/可知日和每次采集时间，避免用后来得知的信息冒充当时已知的信息。[1] [2]

MSCI 和 Nasdaq 的方法材料均将参考日、公告日和实施/生效日分开；MSCI 说明对部分标题中的 effective date 是从该日开盘反映变更。CRSP 通过永久证券标识跟踪跨名称和代码变更的证券，避免把 ticker 当成稳定主键。[2] [3] [4]

因此，本项目的最低可审计记录包括：`effective_date`、`valid_boundary`、`announced_at`（有原公告时）、`observed_at`、`source_url`、`source_sha256`、`parser_version`、`status`。如果公开端点只给一张当前成分表，就只记录“采集器在此时观察到的状态”；不回填虚构的历史公告时间。

## 中国指数规则与来源

中证《股票指数样本调整规则》适用于其管理的境内外股票指数，但具体编制方案另有说明时以方案为准。规则区分年度、半年度、季度周期，规定常见生效日期与数据截止日，并列出退市、并购、停牌、风险警示、快速进入、行业/互联互通/ESG 资格等临时事件。备选名单在定期调整结果披露后生效。这意味着“公告日不等于成分生效日”，且仅靠半年调样名单无法覆盖临时调整。[5]

中证 A500 方案写明每半年调整一次，通常在 6 月和 12 月第二个星期五后的下一交易日实施；每次样本比例一般不超过 10%，并设缓冲区和临时调整规则。中证1000也采用半年调整，且另有退市、合并等临时处理规则。[6] [7]

中证官网指数浏览器提供 CSI、SSE、SZSE、BSE 系列目录；公开列表接口含指数代码、资产类别与地域字段，首版据此发现境内股票类候选，而不是用少量热门代码冒充全覆盖。[13] 国证官网也提供指数目录与当前样本文件。虽然 AKShare 将国证下载接口命名为“历史样本”，实际抽检的深证成指文件只含一个日期状态；对多个代表指数请求官方“历史调样”文件，网站返回“文件不存在”。因此不能用该端点回填完整历史；代码把国证文件按当前观测状态处理，依赖每日差分从启用后开始积累。国证数据服务页明确将样本股清单、样本股权重、公司行为和样本调整名单列为数据产品，指出相关服务需签数据服务协议，部分需付费。故本项目只把下载器作为个人私有采集适配器，不将采集结果发布到公开仓库。[8] [9]

上交所提供指数目录和“信息披露及动态”栏目，公告可直接包含调样名单及实施日；适合从公告附件核实事件，而不宜假定所有指数都存在统一的多年历史 API。[10] 北交所北证50官方页面提供成分列表、编制方案和逐期调整公告，页面覆盖自 2022 年以来的多期样本调整。[11]

CIIS 中证指数基本面数据介绍包含当日收盘权重、次日开盘权重、拟调入样本、公司行为和除数，技术连接注明需获数据牌照许可。它是机构级日度 PIT 的对照基准，但不是免费的开源数据源。[12]

## 工程最佳实践

1. **分开有效时间与知悉时间。** 回测“某日实际在指数里”按生效时间查；回测“当时策略可知道什么”按公告/首次观测时间查。
2. **保留修订版本，不静默覆盖。** 存原始来源 URL、响应 SHA-256、解析器版本和观测时间。发生源文件更正时新增版本并保留旧版本证据。
3. **证券代码不能是永久主键。** 代码、简称、交易所和证券生命周期会变化；首版保存源证券代码与市场标识，后续应接入有许可的证券主数据映射和稳定 ID。
4. **覆盖必须可见。** “无样本变化”“采集失败”“来源未公开”“商业许可不可用”和“尚未支持”是不同状态。失败不能被编码为无变化。
5. **用官方公告验证事件。** CSI/CNI/SSE/BSE 各维护自有目录、方法学和公告；抓到当前快照只能证明该时点观察到的状态，不等于公告已证实准确生效日。
6. **数据与代码分开授权。** 开源代码许可不自动授权发布指数成分数据。公共仓库仅存代码/文档，私有数据仓库存采集输出；需要公开分发时应先取得指数方/数据商许可。

## 仍未消除的缺口

本次未发现单一免费、统一并明确允许再分发的服务，能覆盖所有 A 股指数、全部历史成分、临时调整、每日权重、公司行为和除数。公开中证当前成分文件可以补充一次性快照；国证历史文件对代表性代码只返回最新状态，历史调样下载也缺档。私有自动采集因此从启用日起每日积累并保留来源/观测时间，不能把上线前的缺口伪造成历史 PIT。若目标是可用于生产回测的完整每日 PIT，需接入授权数据供应商，并明确使用、存储和再分发许可。

## 来源

[1]: https://developers.lseg.com/en/article-catalog/article/building-historical-index-constituents "LSEG：Building historical index constituents"
[2]: https://www.msci.com/downloads/web/msci-com/indexes/data-model/MSCI-Constituent-Event-History-Factsheet.pdf "MSCI Constituent Event History Modules"
[3]: https://indexes.nasdaq.com/docs/Methodology_NDX.pdf "Nasdaq-100 Index Methodology"
[4]: https://indexes.morningstar.com/research-data-products/permno "CRSP/Morningstar：Permanent Identifiers"
[5]: https://oss-ch.csindex.com.cn/notice/20251114142128-%E3%80%8A%E4%B8%AD%E8%AF%81%E6%8C%87%E6%95%B0%E6%9C%89%E9%99%90%E5%85%AC%E5%8F%B8%E8%82%A1%E7%A5%A8%E6%A0%B7%E6%9C%AC%E8%B0%83%E6%95%B4%E8%A7%84%E5%88%99%E3%80%8B.pdf "中证指数有限公司股票指数样本调整规则 V1.2"
[6]: https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/zh_CN/000510_Index_Methodology_cn.pdf "中证 A500 指数编制方案"
[7]: https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/zh_CN/20231208175402-000852_Index_Methodology_cn.pdf "中证1000指数编制方案"
[8]: https://www.cnindex.com.cn/module/index-detail.html "国证指数详情与样本历史"
[9]: https://www.cnindex.com.cn/zh_services/index_agent/index.html?act_menu=4&act_service=4 "国证指数服务与数据产品授权"
[10]: https://www.sse.com.cn/market/sseindex/diclosure/ "上交所指数信息披露及动态"
[11]: https://www.bseinfo.net/market_data/bse_indices/bse_bz50.html "北交所北证50指数"
[12]: https://www.ciis.com.hk/hongkong/sc/idata/csifundamentaldata/index.shtml "CIIS 中证指数基本面数据"
[13]: https://www.csindex.com.cn/zh-CN/indices/family/list "中证指数官网指数浏览器：CSI/SSE/SZSE/BSE 系列"
