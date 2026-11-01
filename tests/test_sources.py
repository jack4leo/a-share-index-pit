import unittest

import pandas as pd

from a_share_index_pit.models import IndexRef
from a_share_index_pit.sources import _normalize_cni, _normalize_csindex, is_a_share_equity_code


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


if __name__ == "__main__":
    unittest.main()
