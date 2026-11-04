import json
import unittest
from unittest.mock import patch

import pandas as pd

from a_share_index_pit.classification import classify_cni, classify_csindex
from a_share_index_pit.models import IndexRef
from a_share_index_pit.sources import (
    _normalize_cni,
    _normalize_csindex,
    discover_cni,
    discover_csindex,
    fetch_eastmoney_current,
    is_a_share_equity_code,
)


class SourceNormalizationTests(unittest.TestCase):
    def setUp(self):
        self.ref = IndexRef("CNI", "399001", "深证成指", "https://www.cnindex.com.cn/", "CNI")

    def test_cni_history_is_grouped_by_source_date(self):
        frame = pd.DataFrame([
            {"日期": "2024-06-17", "样本代码": "1", "样本简称": "平安银行", "权重": 0.5},
            {"日期": "2024-06-17", "样本代码": "300750", "样本简称": "宁德时代", "权重": 0.5},
            {"日期": "2024-12-16", "样本代码": "1", "样本简称": "平安银行", "权重": 0.4},
            {"日期": "2024-12-16", "样本代码": "600000", "样本简称": "浦发银行", "权重": 0.6},
        ])
        snapshots = _normalize_cni(frame, self.ref, "https://source/history", "abc")
        self.assertEqual([snap.source_date for snap in snapshots], ["2024-06-17", "2024-12-16"])
        self.assertEqual(snapshots[0].members[0]["security_code"], "000001")
        self.assertEqual(len(snapshots[1].members), 2)
        self.assertEqual(snapshots[0].source_sha256, "abc")

    def test_csindex_current_snapshot_fields(self):
        frame = pd.DataFrame([
            {"日期Date": "20261030", "成份券代码Constituent Code": "600000", "成份券名称Constituent Name": "浦发银行", "权重Weight": 1.2},
            {"日期Date": "20261030", "成份券代码Constituent Code": "000001", "成份券名称Constituent Name": "平安银行", "权重Weight": 0.8},
        ])
        snapshots = _normalize_csindex(frame, self.ref, "https://source/cons.xls", "def")
        self.assertEqual(snapshots[0].source_date, "2026-10-30")
        self.assertEqual({m["security_code"] for m in snapshots[0].members}, {"000001", "600000"})

    def test_eastmoney_fallback_uses_only_latest_trade_date_members(self):
        payload = {"result": {"data": [
            {"TRADE_DATE": "2026-01-01", "SECURITY_CODE": "000001"},
            {"TRADE_DATE": "2026-02-01", "SECURITY_CODE": "000002"},
            {"TRADE_DATE": "", "SECURITY_CODE": "000003"},
        ]}}

        class Response:
            content = json.dumps(payload).encode("utf-8")

            def raise_for_status(self):
                return None

        class Session:
            def get(self, _url, **_kwargs):
                return Response()

        result = fetch_eastmoney_current(Session(), self.ref)
        self.assertEqual(result.status, "ok_secondary")
        self.assertEqual(result.snapshots[0].source_date, "2026-02-01")
        self.assertEqual(
            [member["security_code"] for member in result.snapshots[0].members],
            ["000002"],
        )

    def test_a_share_code_filter(self):
        valid = ["000001", "300750", "302132", "600000", "688001", "920001", "830799"]
        invalid = ["399001", "510300", "900901", "200002", "00700", "600000.SH"]
        for code in valid:
            with self.subTest(code=code):
                self.assertTrue(is_a_share_equity_code(code))
        for code in invalid:
            with self.subTest(code=code):
                self.assertFalse(is_a_share_equity_code(code))

    def test_cni_catalog_accepts_980_codes_and_uses_official_visibility(self):
        payload = {
            "total": 5,
            "data": {
                "total": 5,
                "rows": [
                    {"indexcode": "399001", "indexname": "深证成指", "showcnindex": "1", "indextype": "100", "samplesize": 500},
                    {"indexcode": "980001", "indexname": "湾创100", "showcnindex": "1", "indextype": "200", "samplesize": 100},
                    {"indexcode": "98000600", "indexname": "港股通自由现金流（人民币）", "showcnindex": 1, "indextype": "104", "samplesize": 50},
                    {"indexcode": "CESAIT", "indexname": "中华陆股通行业龙头", "showcnindex": "1", "indextype": "203", "samplesize": 30},
                    {"indexcode": "980002", "indexname": "隐藏条目", "showcnindex": "0", "indextype": "200", "samplesize": 100},
                ],
            },
        }
        with patch("a_share_index_pit.sources.request_bytes", return_value=json.dumps(payload).encode()):
            refs = discover_cni(object())

        self.assertEqual({ref.code for ref in refs}, {"399001", "980001", "98000600", "CESAIT"})
        ref_980 = next(ref for ref in refs if ref.code == "980001")
        self.assertEqual(ref_980.source_provider, "CNI_OFFICIAL_CATALOG")
        self.assertIn("index_type=200", ref_980.note)
        self.assertIn("catalog_sample_size=100", ref_980.note)
        self.assertEqual(json.loads(ref_980.source_classification)["indextype"], "200")
        self.assertEqual(ref_980.primary_category, "market_size")
        self.assertEqual(ref_980.universe_scope_tags, ("equity",))

    def test_cni_strategy_code_maps_to_strategy_dimension_and_unknown_code_stays_unknown(self):
        strategy = classify_cni("104")
        self.assertEqual(strategy["primary_category"], "strategy")
        self.assertEqual(strategy["strategy_tags"], ("strategy",))
        self.assertEqual(strategy["universe_scope_tags"], ("equity",))

        unsupported = classify_cni("999")
        self.assertEqual(unsupported["primary_category"], "unknown")
        self.assertEqual(json.loads(unsupported["source_classification"])["indextype"], "999")

        missing = classify_cni("")
        self.assertEqual(missing["primary_category"], "unknown")
        self.assertEqual(missing["source_classification"], "")

    def test_csindex_native_fields_map_only_publisher_supplied_values(self):
        classification = classify_csindex({
            "indexClassify": "行业",
            "indexClassifyEn": "Sector",
            "assetsClassify": "股票",
            "assetsClassifyEn": "Equity",
            "region": "境内",
            "regionEn": "China Mainland",
        })
        self.assertEqual(classification["primary_category"], "sector_industry")
        self.assertEqual(classification["universe_scope_tags"], ("equity",))
        self.assertEqual(classification["geography_region_tags"], ("china_mainland",))
        self.assertEqual(json.loads(classification["source_classification"])["indexClassify"], "行业")

        unsupported = classify_csindex({"indexClassify": "新分类", "indexName": "主题名称"})
        self.assertEqual(unsupported["primary_category"], "unknown")
        self.assertEqual(json.loads(unsupported["source_classification"])["indexClassify"], "新分类")

    def test_csindex_catalog_discovery_persists_native_classification(self):
        row = {
            "indexCode": "000300", "indexName": "沪深300", "assetsClassify": "股票",
            "assetsClassifyEn": "Equity", "region": "境内", "regionEn": "China Mainland",
            "indexClassify": "规模", "indexClassifyEn": "Size",
        }

        class Response:
            def __init__(self, payload):
                self.payload = payload

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        class Session:
            def post(self, _url, json, **_kwargs):
                series = json["indexFilter"]["indexSeries"][0]
                return Response({"code": "200", "total": 1 if series == "1" else 0,
                                 "data": [row] if series == "1" else []})

        refs = discover_csindex(Session(), page_size=10)
        ref = next(item for item in refs if item.code == "000300")
        self.assertEqual(ref.primary_category, "market_size")
        self.assertEqual(ref.universe_scope_tags, ("equity",))
        self.assertEqual(json.loads(ref.source_classification)["indexClassifyEn"], "Size")

    def test_csindex_missing_total_paginates_until_short_page(self):
        def row(code):
            return {"indexCode": code, "indexName": code, "assetsClassify": "股票", "region": "境内"}

        class Response:
            def __init__(self, rows):
                self.payload = {"code": "200", "data": rows}

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        class Session:
            def __init__(self):
                self.calls = []

            def post(self, _url, json, **_kwargs):
                series = json["indexFilter"]["indexSeries"][0]
                page = json["pager"]["pageNum"]
                self.calls.append((series, page))
                if series == "1" and page == 1:
                    return Response([row("000001"), row("000002")])
                if series == "1" and page == 2:
                    return Response([row("000003")])
                return Response([])

        session = Session()
        refs = discover_csindex(session, page_size=2)
        self.assertEqual([ref.code for ref in refs], ["000001", "000002", "000003"])
        self.assertIn(("1", 2), session.calls)

    def test_csindex_missing_total_repeated_full_page_fails_closed(self):
        rows = [
            {"indexCode": code, "indexName": code, "assetsClassify": "股票", "region": "境内"}
            for code in ("000001", "000002")
        ]

        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return {"code": "200", "data": rows}

        class Session:
            def post(self, _url, **_kwargs):
                return Response()

        with self.assertRaisesRegex(ValueError, "repeated a page"):
            discover_csindex(Session(), page_size=2)

    def test_cni_catalog_rejects_incomplete_pagination(self):
        first_page = {
            "data": {"total": 3, "rows": [
                {"indexcode": "980001", "indexname": "湾创100", "showcnindex": "1", "indextype": "200", "samplesize": 100},
                {"indexcode": "399001", "indexname": "深证成指", "showcnindex": "1", "indextype": "100", "samplesize": 500},
            ]},
        }
        second_page = {"data": {"total": 3, "rows": []}}
        with patch(
            "a_share_index_pit.sources.request_bytes",
            side_effect=[json.dumps(first_page).encode(), json.dumps(second_page).encode()],
        ):
            with self.assertRaisesRegex(ValueError, "ended at 2 of 3"):
                discover_cni(object())


if __name__ == "__main__":
    unittest.main()
