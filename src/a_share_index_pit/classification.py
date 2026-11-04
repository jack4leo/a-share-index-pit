from __future__ import annotations

import json
from typing import Any


# CNI's official index-series page uses these indextype values and labels.
# Codes not in this table remain preserved as raw native values but normalize to unknown.
CNI_TYPE_LABELS = {
    "100": "深证指数-规模指数",
    "101": "深证指数-行业指数",
    "102": "深证指数-风格指数",
    "103": "深证指数-主题指数",
    "104": "深证指数-策略指数",
    "105": "深证指数-综合指数",
    "106": "深证指数-债券指数",
    "107": "深证指数-基金指数",
    "108": "深证指数-定制指数",
    "111": "深证指数-多资产指数",
    "199": "深证指数-其他指数",
    "200": "国证指数-规模指数",
    "201": "国证指数-行业指数",
    "202": "国证指数-风格指数",
    "203": "国证指数-主题指数",
    "204": "国证指数-策略指数",
    "205": "国证指数-综合指数",
    "206": "国证指数-债券指数",
    "207": "国证指数-基金指数",
    "208": "国证指数-定制指数",
    "209": "国证指数-人民币指数",
    "210": "国证指数-跨境指数",
    "211": "国证指数-多资产指数",
    "299": "国证指数-其他指数",
    "300": "央视指数-央视指数",
    "401": "国际合作-泛欧交易所",
    "402": "国际合作-柬埔寨证券交易所",
    "403": "国际合作-达卡交易所",
    "500": "中华指数-中华指数",
    "600": "新华指数-新华指数",
    "700": "全球指数-全球指数",
}

CNI_PRIMARY_CATEGORIES = {
    "100": "market_size", "200": "market_size",
    "101": "sector_industry", "201": "sector_industry",
    "102": "style_factor", "202": "style_factor",
    "103": "thematic", "203": "thematic",
    "104": "strategy", "204": "strategy",
    "105": "composite", "205": "composite",
    "106": "fixed_income", "206": "fixed_income",
    "107": "fund", "207": "fund",
    "108": "customized", "208": "customized",
    "209": "currency",
    "210": "cross_border",
    "111": "multi_asset", "211": "multi_asset",
    "199": "other", "299": "other",
}

_CNI_EQUITY_CATEGORIES = {
    "market_size", "sector_industry", "style_factor", "thematic", "strategy", "composite",
}

_CSI_CLASS_CATEGORIES = {
    "规模": "market_size", "size": "market_size",
    "主题": "thematic", "thematic": "thematic",
    "行业": "sector_industry", "sector": "sector_industry",
    "风格": "style_factor", "style": "style_factor",
    "策略": "strategy", "strategy": "strategy",
    "综合": "composite", "composite": "composite", "comprehensive": "composite",
    "信用债": "fixed_income", "credit bond": "fixed_income",
    "利率债": "fixed_income", "interest rate bond": "fixed_income",
    "可转债": "fixed_income", "convertible bond": "fixed_income",
}

_CSI_UNIVERSE = {
    "股票": "equity", "equity": "equity",
    "固定收益": "fixed_income", "fixed income": "fixed_income",
    "基金": "fund", "fund": "fund",
}

_CSI_GEOGRAPHY = {
    "境内": "china_mainland", "china mainland": "china_mainland",
    "沪深港": "china_mainland_hong_kong", "mainland china and hong kong": "china_mainland_hong_kong",
}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _fields(
    native: dict[str, Any],
    primary_category: str,
    universe_scope_tags: tuple[str, ...],
    geography_region_tags: tuple[str, ...],
    style_factor_tags: tuple[str, ...] = (),
    strategy_tags: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "source_classification": _json(native) if native else "",
        "primary_category": primary_category,
        "universe_scope_tags": universe_scope_tags or ("unknown",),
        "geography_region_tags": geography_region_tags or ("unknown",),
        "style_factor_tags": style_factor_tags,
        "strategy_tags": strategy_tags,
    }


def classify_cni(index_type: Any) -> dict[str, Any]:
    """Normalize CNI's official `indextype`; unknown codes are never inferred."""
    code = "" if index_type is None else str(index_type).strip()
    label = CNI_TYPE_LABELS.get(code)
    native: dict[str, Any] = {"indextype": code} if code else {}
    if label:
        native["official_type_label"] = label

    category = CNI_PRIMARY_CATEGORIES.get(code, "unknown")
    if category in _CNI_EQUITY_CATEGORIES:
        universe = ("equity",)
    elif category == "fixed_income":
        universe = ("fixed_income",)
    elif category == "fund":
        universe = ("fund",)
    elif category == "multi_asset":
        universe = ("multi_asset",)
    elif category == "currency":
        universe = ("currency",)
    else:
        universe = ("unknown",)

    geography = ("cross_border",) if category == "cross_border" else ("unknown",)
    styles = ("style",) if category == "style_factor" else ()
    strategies = ("strategy",) if category == "strategy" else ()
    return _fields(native, category, universe, geography, styles, strategies)


def classify_csindex(row: dict[str, Any]) -> dict[str, Any]:
    """Normalize CSI catalog fields while retaining their original values."""
    native_keys = (
        "indexClassify", "indexClassifyEn", "assetsClassify", "assetsClassifyEn",
        "region", "regionEn", "hotSpot", "hotSpotEn",
    )
    native = {key: row[key] for key in native_keys if key in row}
    source_class = str(row.get("indexClassify") or "").strip()
    source_class_en = str(row.get("indexClassifyEn") or "").strip()
    category = _CSI_CLASS_CATEGORIES.get(source_class.casefold(), "unknown")
    if category == "unknown":
        category = _CSI_CLASS_CATEGORIES.get(source_class_en.casefold(), "unknown")

    asset_class = str(row.get("assetsClassify") or "").strip()
    asset_class_en = str(row.get("assetsClassifyEn") or "").strip()
    universe = _CSI_UNIVERSE.get(asset_class.casefold()) or _CSI_UNIVERSE.get(asset_class_en.casefold())
    if not universe:
        universe = "unknown"

    region = str(row.get("region") or "").strip()
    region_en = str(row.get("regionEn") or "").strip()
    geography = _CSI_GEOGRAPHY.get(region.casefold()) or _CSI_GEOGRAPHY.get(region_en.casefold())
    if not geography:
        geography = "unknown"

    # Asset-class fields are explicit publisher data; use them only as a fallback
    # for primary category when the finer classification field is absent.
    if category == "unknown" and not (source_class or source_class_en):
        if universe in {"fixed_income", "fund"}:
            category = universe

    styles = ("style",) if category == "style_factor" else ()
    strategies = ("strategy",) if category == "strategy" else ()
    return _fields(native, category, (universe,), (geography,), styles, strategies)
