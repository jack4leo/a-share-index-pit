from __future__ import annotations

import hashlib
import io
import json
import re
import time
from datetime import date, datetime
from typing import Any

import pandas as pd
import requests

from .classification import classify_cni, classify_csindex
from .models import FetchResult, IndexRef, Snapshot

CNI_CATALOG_URL = "https://www.cnindex.com.cn/index/indexList"
CNI_HISTORY_URL = "https://www.cnindex.com.cn/sample-detail/download-history"
JOINQUANT_CATALOG_URL = "https://www.joinquant.com/data/dict/indexData"
CSINDEX_CATALOG_URL = "https://www.csindex.com.cn/csindex-home/index-list/query-index-item"
CSINDEX_CONS_URL = (
    "https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/"
    "file/autofile/cons/{code}cons.xls"
)
EASTMONEY_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"

HEADERS = {
    "User-Agent": "a-share-index-pit/0.1 (+https://github.com/jack4leo/a-share-index-pit)",
    "Accept": "*/*",
}


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(HEADERS)
    return session


def request_bytes(
    session: requests.Session,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    timeout: tuple[float, float] = (10, 35),
    attempts: int = 3,
) -> bytes:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            response = session.get(url, params=params, timeout=timeout)
            response.raise_for_status()
            return response.content
        except Exception as exc:  # network errors and upstream 5xx are retried
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(1.5 * (2**attempt))
    assert last_error is not None
    raise last_error


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _text(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def _code(value: Any) -> str:
    text = _text(value)
    if not text:
        return ""
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    # Five-character identifiers with a leading zero are common non-mainland
    # tickers (for example, 00700.HK); do not turn them into 000700.
    if text.isdigit() and len(text) == 5 and text.startswith("0"):
        return text
    return text.zfill(6) if text.isdigit() and len(text) <= 6 else text.upper()


def _date(value: Any) -> str:
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.strftime("%Y-%m-%d")
    text = _text(value)
    if not text:
        return ""
    parsed = pd.to_datetime(text, errors="coerce")
    return "" if pd.isna(parsed) else parsed.strftime("%Y-%m-%d")


def is_a_share_equity_code(code: str) -> bool:
    """Conservative mainland A-share code check; B-shares/funds are excluded."""
    value = _code(code)
    if not value.isdigit() or len(value) != 6:
        return False
    # Verified Shenzhen-listed A-share code change: 300114 became 302132 in 2025.
    if value == "302132":
        return True
    return value.startswith(
        (
            "000", "001", "002", "003", "300", "301",  # Shenzhen
            "600", "601", "603", "605", "688", "689",  # Shanghai
            "430", "830", "831", "832", "833", "834", "835", "836",
            "837", "838", "839", "870", "871", "872", "873", "920",  # Beijing
        )
    )


def _publisher_for_joinquant(code: str) -> str:
    if code.startswith("399"):
        return "CNI"
    if code.startswith("899"):
        return "BSE"
    return "CSI_OR_SSE"


def discover_cni(session: requests.Session) -> list[IndexRef]:
    """Discover every visible CNI index from the official catalog."""
    results: list[IndexRef] = []
    page_size = 2000
    page_num = 1
    total: int | None = None
    received = 0
    catalog_url = "https://www.cnindex.com.cn/zh_indices/sese/index.html?act_menu=1&index_type=-1"
    while total is None or received < total:
        body = request_bytes(
            session,
            CNI_CATALOG_URL,
            params={"channelCode": "-1", "rows": str(page_size), "pageNum": str(page_num)},
        )
        payload = json.loads(body.decode("utf-8-sig"))
        data = payload.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("rows"), list):
            raise ValueError("CNI official catalog response has no data.rows list")
        rows = data["rows"]
        if total is None:
            total = int(data.get("total") or payload.get("total") or len(rows))
            if total <= 0:
                raise ValueError("CNI official catalog reported no rows")
        if not rows and received < total:
            raise ValueError(f"CNI official catalog ended at {received} of {total} rows")
        for row in rows:
            code = _code(row.get("indexcode"))
            name = _text(row.get("indexname"))
            visible = _text(row.get("showcnindex")).casefold() in {"1", "true", "yes"}
            if not visible or not re.fullmatch(r"[A-Z0-9]{1,16}", code) or not name:
                continue
            sample_size = pd.to_numeric(row.get("samplesize"), errors="coerce")
            index_type = _text(row.get("indextype"))
            classification = classify_cni(index_type)
            note = f"official_visible=1; index_type={index_type or 'unknown'}; catalog_sample_size=" + (
                "unknown" if pd.isna(sample_size) else str(int(sample_size))
            )
            results.append(
                IndexRef(
                    provider="CNI",
                    code=code,
                    name=name,
                    catalog_url=catalog_url,
                    source_provider="CNI_OFFICIAL_CATALOG",
                    note=note,
                    **classification,
                )
            )
        received += len(rows)
        if received < total:
            page_num += 1
    if received < total:
        raise ValueError(f"CNI official catalog is incomplete: received {received} of {total} rows")
    if not results:
        raise ValueError("CNI official catalog contained no visible valid index entries")
    return results


def discover_csindex(session: requests.Session, page_size: int = 200) -> list[IndexRef]:
    """Discover mainland equity indexes from CSI's official index explorer."""
    families = {
        "1": "CSI",
        "2": "SSE",
        "3": "SZSE",
        "7": "BSE",
    }
    results: list[IndexRef] = []
    for series_id, family_name in families.items():
        page_num = 1
        total = None
        received = 0
        while total is None or (page_num - 1) * page_size < total:
            body = {
                "sorter": {"sortField": "null", "sortOrder": None},
                "pager": {"pageNum": page_num, "pageSize": page_size},
                "searchInput": None,
                "indexFilter": {
                    "indexSeries": [series_id], "indexClassify": None, "region": None,
                    "hotSpot": None, "currency": None, "ifWeightCapped": None,
                    "ifCustomized": None, "ifTracked": None, "indexCompliance": None,
                },
            }
            last_error: Exception | None = None
            payload = None
            for attempt in range(3):
                try:
                    response = session.post(
                        CSINDEX_CATALOG_URL,
                        json=body,
                        headers={
                            "Content-Type": "application/json;charset=UTF-8",
                            "Referer": "https://www.csindex.com.cn/zh-CN/indices/family/list",
                        },
                        timeout=(10, 35),
                    )
                    response.raise_for_status()
                    payload = response.json()
                    if str(payload.get("code")) != "200":
                        raise ValueError(f"CSI catalog API returned {payload.get('code')}: {payload.get('msg')}")
                    break
                except Exception as exc:
                    last_error = exc
                    if attempt < 2:
                        time.sleep(1.5 * (2**attempt))
            if payload is None:
                raise RuntimeError(f"CSI catalog series {series_id} failed: {last_error}")
            rows = payload.get("data") or []
            if not isinstance(rows, list):
                raise ValueError(f"unexpected CSI catalog page type: {type(rows).__name__}")
            if total is None:
                total = int(payload.get("total") or 0)
            received += len(rows)
            for row in rows:
                code = _code(row.get("indexCode"))
                name = _text(row.get("indexName"))
                asset_class = _text(row.get("assetsClassify") or row.get("assetsClassifyEn"))
                region = _text(row.get("region") or row.get("regionEn"))
                if not code or not name or not re.fullmatch(r"\d{6}", code):
                    continue
                if asset_class not in ("股票", "Equity") or region not in ("境内", "China Mainland"):
                    continue
                classification = classify_csindex(row)
                # 399xxx codes can also appear in CSI's cross-publisher directory;
                # normalize them to the CNI publisher namespace.
                publisher = "CNI" if code.startswith("399") else ("BSE" if code.startswith("899") else family_name)
                results.append(IndexRef(
                    provider=publisher,
                    code=code,
                    name=name,
                    catalog_url="https://www.csindex.com.cn/zh-CN/indices/family/list",
                    source_provider="CSINDEX_OFFICIAL_CATALOG",
                    note=f"series={series_id}; asset_class={asset_class}; region={region}",
                    **classification,
                ))
            if not rows:
                if received < total:
                    raise ValueError(f"CSI catalog series {series_id} ended at {received} of {total} rows")
                break
            if len(rows) < page_size:
                if received < total:
                    raise ValueError(f"CSI catalog series {series_id} is incomplete: received {received} of {total} rows")
                break
            page_num += 1

    if not results:
        raise ValueError("CSI official catalog contained no eligible mainland equity indexes")
    return results


def discover_joinquant(session: requests.Session) -> list[IndexRef]:
    """Use a broad public index directory for CSI/SSE/BSE discovery only."""
    body = request_bytes(session, JOINQUANT_CATALOG_URL)
    tables = pd.read_html(io.StringIO(body.decode("utf-8", errors="replace")))
    if not tables:
        raise ValueError("JoinQuant index directory contained no HTML table")
    frame = tables[0]
    # The source table currently starts with a code column; tolerate column-name changes.
    code_col = next((c for c in frame.columns if "代码" in str(c)), frame.columns[0])
    name_col = next((c for c in frame.columns if "简称" in str(c) or "名称" in str(c)), frame.columns[1])
    results: list[IndexRef] = []
    seen: set[str] = set()
    for _, row in frame.iterrows():
        raw_code = _text(row.get(code_col))
        code = _code(raw_code.split(".")[0])
        name = _text(row.get(name_col))
        if not name or not re.fullmatch(r"(?:000|899)\d{3}", code):
            continue
        publisher = _publisher_for_joinquant(code)
        if code in seen:
            continue
        seen.add(code)
        results.append(
            IndexRef(
                provider=publisher,
                code=code,
                name=name,
                catalog_url=JOINQUANT_CATALOG_URL,
                source_provider="JOINQUANT_CATALOG",
                note="directory_only; membership fetched from official/secondary source",
            )
        )
    # Keep essential candidates discoverable if the directory is temporarily down.
    essential = [("000510", "中证A500", "CSI_OR_SSE"), ("000852", "中证1000", "CSI_OR_SSE"), ("899050", "北证50", "BSE")]
    for code, name, publisher in essential:
        if code not in seen:
            results.append(
                IndexRef(provider=publisher, code=code, name=name, catalog_url=JOINQUANT_CATALOG_URL,
                         source_provider="SEED", note="seed candidate; validate against official catalog")
            )
    return results


def discover_indexes(session: requests.Session) -> tuple[list[IndexRef], list[dict[str, str]]]:
    refs: dict[tuple[str, str], IndexRef] = {}
    catalog_errors: list[dict[str, str]] = []
    for label, discoverer in (("CNI", discover_cni), ("CSINDEX", discover_csindex)):
        try:
            for ref in discoverer(session):
                refs.setdefault((ref.provider, ref.code), ref)
        except Exception as exc:
            catalog_errors.append({"catalog": label, "status": "catalog_fetch_failed", "message": str(exc)[:500]})
    if any(row["catalog"] == "CSINDEX" for row in catalog_errors):
        try:
            for ref in discover_joinquant(session):
                refs.setdefault((ref.provider, ref.code), ref)
        except Exception as exc:
            catalog_errors.append({"catalog": "JOINQUANT_FALLBACK", "status": "catalog_fetch_failed", "message": str(exc)[:500]})
    ordered = sorted(refs.values(), key=lambda item: (item.provider, item.code))
    return ordered, catalog_errors


def _read_excel(content: bytes) -> pd.DataFrame:
    try:
        return pd.read_excel(io.BytesIO(content))
    except Exception as exc:
        raise ValueError(f"could not parse source spreadsheet: {exc}") from exc


def _find_column(frame: pd.DataFrame, candidates: tuple[str, ...]) -> Any | None:
    for col in frame.columns:
        label = str(col).strip()
        if any(candidate in label for candidate in candidates):
            return col
    return None


def _normalize_cni(frame: pd.DataFrame, index: IndexRef, source_url: str, digest: str) -> list[Snapshot]:
    date_col = _find_column(frame, ("日期", "date"))
    code_col = _find_column(frame, ("样本代码", "成分券代码", "代码", "security_code"))
    name_col = _find_column(frame, ("样本简称", "成分券名称", "简称", "name"))
    weight_col = _find_column(frame, ("权重", "weight"))
    if date_col is None or code_col is None:
        raise ValueError(f"unexpected CNI history columns: {list(frame.columns)}")
    rows: dict[str, list[dict[str, Any]]] = {}
    for _, row in frame.iterrows():
        source_date = _date(row.get(date_col))
        code = _code(row.get(code_col))
        if not source_date or not code:
            continue
        member: dict[str, Any] = {"security_code": code}
        if name_col is not None:
            member["security_name"] = _text(row.get(name_col))
        if weight_col is not None:
            weight = pd.to_numeric(row.get(weight_col), errors="coerce")
            if not pd.isna(weight):
                member["weight_source_value"] = float(weight)
        rows.setdefault(source_date, []).append(member)
    confidence = "official_current_state" if len(rows) == 1 else "official_dated_states"
    return [
        Snapshot(index, source_date, sorted(members, key=lambda item: item["security_code"]),
                 "CNI_OFFICIAL_SAMPLE_FILE", source_url, digest, "unknown", confidence)
        for source_date, members in sorted(rows.items())
    ]


def _normalize_csindex(frame: pd.DataFrame, index: IndexRef, source_url: str, digest: str) -> list[Snapshot]:
    date_col = _find_column(frame, ("日期", "date"))
    code_col = _find_column(frame, ("成份券代码", "成分券代码", "样本代码", "security_code"))
    name_col = _find_column(frame, ("成份券名称", "成分券名称", "样本简称", "security_name"))
    weight_col = _find_column(frame, ("权重", "weight"))
    if date_col is None or code_col is None:
        raise ValueError(f"unexpected CSI spreadsheet columns: {list(frame.columns)}")
    grouped: dict[str, list[dict[str, Any]]] = {}
    for _, row in frame.iterrows():
        source_date = _date(row.get(date_col))
        code = _code(row.get(code_col))
        if not source_date or not code:
            continue
        member: dict[str, Any] = {"security_code": code}
        if name_col is not None:
            member["security_name"] = _text(row.get(name_col))
        if weight_col is not None:
            weight = pd.to_numeric(row.get(weight_col), errors="coerce")
            if not pd.isna(weight):
                member["weight_source_value"] = float(weight)
        grouped.setdefault(source_date, []).append(member)
    return [
        Snapshot(index, source_date, sorted(members, key=lambda item: item["security_code"]),
                 "CSINDEX_OFFICIAL_FILE", source_url, digest, "source_date", "official_file_state")
        for source_date, members in sorted(grouped.items())
    ]


def fetch_cni_sample_file(session: requests.Session, index: IndexRef) -> FetchResult:
    url = CNI_HISTORY_URL
    params = {"indexcode": index.code}
    content = request_bytes(session, url, params=params)
    digest = sha256_bytes(content)
    frame = _read_excel(content)
    snapshots = _normalize_cni(frame, index, f"{url}?indexcode={index.code}", digest)
    if not snapshots:
        return FetchResult(index, "empty_source", source_provider="CNI_OFFICIAL_SAMPLE_FILE",
                           source_url=url, source_sha256=digest, message="sample export contained no dated members")
    return FetchResult(index, "ok", snapshots, "CNI_OFFICIAL_SAMPLE_FILE", url, digest)


def fetch_csindex_current(session: requests.Session, index: IndexRef) -> FetchResult:
    url = CSINDEX_CONS_URL.format(code=index.code)
    content = request_bytes(session, url)
    digest = sha256_bytes(content)
    frame = _read_excel(content)
    snapshots = _normalize_csindex(frame, index, url, digest)
    if not snapshots:
        return FetchResult(index, "empty_source", source_provider="CSINDEX_OFFICIAL_FILE",
                           source_url=url, source_sha256=digest, message="constituent workbook contained no dated rows")
    # The official `cons.xls` file is the current component list; keep only its latest date.
    latest_date = max(snapshot.source_date for snapshot in snapshots)
    snapshots = [snapshot for snapshot in snapshots if snapshot.source_date == latest_date]
    for snapshot in snapshots:
        snapshot.confidence = "official_current_state"
        snapshot.valid_boundary = "unknown"
    return FetchResult(index, "ok", snapshots, "CSINDEX_OFFICIAL_FILE", url, digest)


def fetch_eastmoney_current(session: requests.Session, index: IndexRef) -> FetchResult:
    """Optional third-party fallback; never label as official or historical."""
    params = {
        "reportName": "RPT_INDEX_CONSTITUENT",
        "columns": "ALL",
        "filter": f'(INDEX_CODE="{index.code}")',
        "pageNumber": 1,
        "pageSize": 3000,
        "source": "WEB",
        "client": "WEB",
    }
    content = request_bytes(session, EASTMONEY_URL, params=params)
    digest = sha256_bytes(content)
    payload = json.loads(content.decode("utf-8-sig"))
    data = ((payload.get("result") or {}).get("data") or [])
    if not data:
        return FetchResult(index, "no_data", source_provider="EASTMONEY_SECONDARY",
                           source_url=EASTMONEY_URL, source_sha256=digest,
                           message=str(payload.get("message") or "empty result")[:300])
    dates = {_date(item.get("TRADE_DATE")) for item in data}
    dates.discard("")
    source_date = max(dates) if dates else ""
    members = []
    for item in data:
        code = _code(item.get("SECURITY_CODE"))
        if not code:
            continue
        members.append({"security_code": code, "security_name": _text(item.get("SECURITY_NAME_ABBR"))})
    snapshot = Snapshot(index, source_date, sorted(members, key=lambda item: item["security_code"]),
                        "EASTMONEY_SECONDARY", EASTMONEY_URL, digest, "unknown", "secondary_observed_state")
    return FetchResult(index, "ok_secondary", [snapshot], "EASTMONEY_SECONDARY", EASTMONEY_URL, digest)


def fetch_index(session: requests.Session, index: IndexRef, allow_secondary: bool = True) -> FetchResult:
    """Fetch the primary index-family source, then an explicitly labeled fallback."""
    try:
        if index.provider == "CNI":
            primary = fetch_cni_sample_file(session, index)
        else:
            primary = fetch_csindex_current(session, index)
        if primary.status == "ok":
            return primary
        primary_error = primary.message or primary.status
    except Exception as exc:
        primary_error = str(exc)
    if allow_secondary:
        try:
            fallback = fetch_eastmoney_current(session, index)
            if fallback.status.startswith("ok"):
                fallback.message = f"secondary fallback; primary failed: {primary_error[:200]}"
                return fallback
            primary_error = f"primary={primary_error}; secondary={fallback.message}"
        except Exception as exc:
            primary_error = f"primary={primary_error}; secondary={str(exc)}"
    return FetchResult(index, "fetch_failed", source_provider=index.source_provider,
                       source_url="", message=primary_error[:500])
