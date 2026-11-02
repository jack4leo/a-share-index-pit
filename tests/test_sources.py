import json
import unittest
from unittest.mock import patch

import pandas as pd

from a_share_index_pit.models import IndexRef
from a_share_index_pit.sources import (
    _normalize_cni,
    _normalize_csindex,
    discover_cni,
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
