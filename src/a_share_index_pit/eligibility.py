from __future__ import annotations

import json
from typing import Any


IN_SCOPE = "in_scope"
OUT_OF_SCOPE = "out_of_scope"
UNKNOWN = "unknown"
ELIGIBILITY_STATUSES = {IN_SCOPE, OUT_OF_SCOPE, UNKNOWN}

# CNI's publisher-native index-type codes that identify equity-index families.
# Strategy/style/thematic/composite families are deliberately included.
_CNI_EQUITY_TYPES = {
    "100", "101", "102", "103", "104", "105",
    "200", "201", "202", "203", "204", "205",
}

# These official CNI families identify non-stock instruments or a non-single-stock
# asset universe. Other/foreign/cross-border/custom families remain unknown unless
# another publisher field supplies explicit evidence.
_CNI_NON_STOCK_TYPES = {
    "106": "fixed-income index family",
    "107": "fund index family",
    "111": "multi-asset index family",
    "206": "fixed-income index family",
    "207": "fund index family",
    "209": "currency index family",
    "211": "multi-asset index family",
}

_CNI_OFFICIAL_INDEX_LIST_URL = (
    "https://www.cnindex.com.cn/index_1020/brochures_1593/201912/"
    "P020260929502519176457.xls"
)
_CNI_CN6109_METHODOLOGY_URL = "https://www.cnindex.com.cn/docs/gz_399625.pdf"
_CNI_980025_ANNOUNCEMENT_URL = (
    "https://www.cnindex.com.cn/zh_information/notices_news/2019/201912/"
    "t20191224_15556.html?act_menu=2"
)

# Exact-code supplements from the CNI official Index List workbook (2026-09-29).
# They preserve that workbook's native asset class and coverage values. A mixed
# A-share/CDR universe remains reviewable rather than being excluded.
_CNI_OFFICIAL_ASSET_CLASS_EXCEPTIONS = {
    "980025": ("其它", "其他", OUT_OF_SCOPE,
               "CNI lists this as asset class 'other' with coverage 'other'; its official announcement defines a market-development measurement index, not a stock universe."),
    "CN5061": ("股票", "深市A股", IN_SCOPE,
               "CNI lists a stock asset class and Shenzhen A-share coverage."),
    "CN5062": ("股票", "A股和红筹企业发行的存托凭证", UNKNOWN,
               "CNI identifies stocks, but the published coverage mixes A shares and red-chip depositary receipts; retained for review and collection."),
    "CN6070": ("基金", "中国开放式主动管理股票型基金", OUT_OF_SCOPE,
               "CNI lists the asset class as funds, not stocks."),
    "CN6071": ("基金", "中国开放式主动管理混合型基金", OUT_OF_SCOPE,
               "CNI lists the asset class as funds, not stocks."),
    "CN6072": ("基金", "中国开放式主动管理债券型基金", OUT_OF_SCOPE,
               "CNI lists the asset class as funds, not stocks."),
    "CN6109": ("股票", "深市原中小板和创业板市场", IN_SCOPE,
               "CNI lists a stock asset class; its official SME-ChiNext 100 methodology defines the underlying universe as Shenzhen-listed A shares."),
    "CNB00013": ("债券", "境内证券交易所和银行间市场债券", OUT_OF_SCOPE,
                 "CNI lists the asset class as bonds, not stocks."),
    "CNB00014": ("债券", "境内证券交易所和银行间市场债券", OUT_OF_SCOPE,
                 "CNI lists the asset class as bonds, not stocks."),
    "CNB00015": ("债券", "境内证券交易所和银行间市场债券", OUT_OF_SCOPE,
                 "CNI lists the asset class as bonds, not stocks."),
    "CNB10013": ("债券", "境内证券交易所和银行间市场债券", OUT_OF_SCOPE,
                 "CNI lists the asset class as bonds, not stocks."),
    "CNB10014": ("债券", "境内证券交易所和银行间市场债券", OUT_OF_SCOPE,
                 "CNI lists the asset class as bonds, not stocks."),
    "CNB10015": ("债券", "境内证券交易所和银行间市场债券", OUT_OF_SCOPE,
                 "CNI lists the asset class as bonds, not stocks."),
    "CNB20013": ("债券", "境内证券交易所和银行间市场债券", OUT_OF_SCOPE,
                 "CNI lists the asset class as bonds, not stocks."),
    "CNB20014": ("债券", "境内证券交易所和银行间市场债券", OUT_OF_SCOPE,
                 "CNI lists the asset class as bonds, not stocks."),
    "CNB20015": ("债券", "境内证券交易所和银行间市场债券", OUT_OF_SCOPE,
                 "CNI lists the asset class as bonds, not stocks."),
}

_CSI_EQUITY_ASSET_VALUES = {"股票", "equity", "equities", "stock", "stocks"}
_CSI_NON_STOCK_ASSET_VALUES = {
    "债券": "fixed-income asset class",
    "固定收益": "fixed-income asset class",
    "bond": "fixed-income asset class",
    "bonds": "fixed-income asset class",
    "fixed income": "fixed-income asset class",
    "基金": "fund asset class",
    "fund": "fund asset class",
    "funds": "fund asset class",
    "多资产": "multi-asset class",
    "multi asset": "multi-asset class",
    "multi-asset": "multi-asset class",
    "商品": "commodity asset class",
    "大宗商品": "commodity asset class",
    "commodity": "commodity asset class",
    "commodities": "commodity asset class",
    "货币": "currency asset class",
    "外汇": "currency asset class",
    "currency": "currency asset class",
    "fx": "currency asset class",
}
_CSI_MAINLAND_REGIONS = {"境内", "china mainland", "mainland china"}


def _json_evidence(values: dict[str, Any]) -> str:
    return json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def assess_cni(
    index_type: Any,
    *,
    source_provider: str = "CNI_OFFICIAL_CATALOG",
    index_code: str = "",
) -> dict[str, str]:
    """Assess scope from CNI-native fields or a documented exact-code source record."""
    code = "" if index_type is None else str(index_type).strip()
    evidence = {"indextype": code} if code else {}
    source = f"{source_provider}.indextype"
    supplemental = _CNI_OFFICIAL_ASSET_CLASS_EXCEPTIONS.get(index_code)
    if supplemental:
        asset_class, coverage_scope, status, reason = supplemental
        evidence = {
            "indexcode": index_code,
            "indextype": code,
            "asset_class": asset_class,
            "coverage_scope": coverage_scope,
            "official_index_list_url": _CNI_OFFICIAL_INDEX_LIST_URL,
        }
        source = f"{source_provider}.asset_class+coverage_scope"
        if index_code == "980025":
            evidence["supporting_announcement_url"] = _CNI_980025_ANNOUNCEMENT_URL
        if index_code == "CN6109":
            evidence["underlying_methodology_url"] = _CNI_CN6109_METHODOLOGY_URL
            source += "+CNINDEX_METHODOLOGY"
        return {
            "eligibility_status": status,
            "eligibility_reason": reason,
            "eligibility_source": source,
            "eligibility_evidence": _json_evidence(evidence),
        }
    if code in _CNI_EQUITY_TYPES:
        return {
            "eligibility_status": IN_SCOPE,
            "eligibility_reason": f"CNI native indextype={code} identifies an equity-index family, including stock strategies where applicable.",
            "eligibility_source": source,
            "eligibility_evidence": _json_evidence(evidence),
        }
    if code in _CNI_NON_STOCK_TYPES:
        family = _CNI_NON_STOCK_TYPES[code]
        return {
            "eligibility_status": OUT_OF_SCOPE,
            "eligibility_reason": f"CNI native indextype={code} explicitly identifies a {family}, not a stock index.",
            "eligibility_source": source,
            "eligibility_evidence": _json_evidence(evidence),
        }
    detail = f"indextype={code}" if code else "indextype is absent"
    return {
        "eligibility_status": UNKNOWN,
        "eligibility_reason": f"CNI native {detail} does not establish stock or non-stock eligibility; retained for review and collection.",
        "eligibility_source": source,
        "eligibility_evidence": _json_evidence(evidence),
    }


def assess_csindex(row: dict[str, Any], *, source_provider: str = "CSINDEX_OFFICIAL_CATALOG") -> dict[str, str]:
    """Assess scope only from CSI's publisher-provided asset class and region."""
    evidence = {
        key: row[key]
        for key in ("assetsClassify", "assetsClassifyEn", "region", "regionEn")
        if key in row
    }
    asset_values = [
        str(row.get(key) or "").strip().casefold()
        for key in ("assetsClassify", "assetsClassifyEn")
    ]
    region_values = [
        str(row.get(key) or "").strip().casefold()
        for key in ("region", "regionEn")
    ]
    source = f"{source_provider}.assetsClassify+region"
    non_stock = next((
        _CSI_NON_STOCK_ASSET_VALUES[value]
        for value in asset_values
        if value in _CSI_NON_STOCK_ASSET_VALUES
    ), None)
    if non_stock:
        return {
            "eligibility_status": OUT_OF_SCOPE,
            "eligibility_reason": f"CSI native asset-class field explicitly identifies a {non_stock}, not a stock index.",
            "eligibility_source": f"{source_provider}.assetsClassify",
            "eligibility_evidence": _json_evidence(evidence),
        }

    has_equity_evidence = any(value in _CSI_EQUITY_ASSET_VALUES for value in asset_values)
    has_mainland_evidence = any(value in _CSI_MAINLAND_REGIONS for value in region_values)
    if has_equity_evidence and has_mainland_evidence:
        return {
            "eligibility_status": IN_SCOPE,
            "eligibility_reason": "CSI native asset-class and region fields identify mainland equity; index category (including strategy) does not exclude it.",
            "eligibility_source": source,
            "eligibility_evidence": _json_evidence(evidence),
        }

    if has_equity_evidence:
        reason = "CSI identifies an equity asset class but does not explicitly establish mainland-only scope; retained as unknown for review and collection."
    else:
        reason = "CSI native asset-class evidence is absent or unsupported; retained as unknown for review and collection."
    return {
        "eligibility_status": UNKNOWN,
        "eligibility_reason": reason,
        "eligibility_source": source,
        "eligibility_evidence": _json_evidence(evidence),
    }


def unknown_eligibility(*, source_provider: str = "") -> dict[str, str]:
    """Construct an explicit reviewable unknown result where no supported evidence exists."""
    return {
        "eligibility_status": UNKNOWN,
        "eligibility_reason": "No supported publisher-native eligibility evidence is available; retained for review and collection.",
        "eligibility_source": source_provider,
        "eligibility_evidence": "{}",
    }
