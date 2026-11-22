import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from a_share_index_pit.collector import _merge_incomplete_catalog, collect
from a_share_index_pit.models import FetchResult, IndexRef


class CollectorReliabilityTests(unittest.TestCase):
    def test_only_confirmed_out_of_scope_is_skipped_and_catalog_keeps_all_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            in_scope = IndexRef(
                "CSI", "931001", "股票策略", "https://csi.test", "CSINDEX_OFFICIAL_CATALOG",
                primary_category="strategy", universe_scope_tags=("equity",),
                eligibility_status="in_scope", eligibility_reason="native equity evidence",
                eligibility_source="CSINDEX_OFFICIAL_CATALOG.assetsClassify+region",
                eligibility_evidence='{"assetsClassify":"股票","region":"境内"}',
            )
            unknown = IndexRef(
                "CNI", "CN6010", "股票策略候选", "https://cni.test", "CNI_OFFICIAL_CATALOG",
                eligibility_status="unknown", eligibility_reason="unresolved native evidence",
            )
            out_of_scope = IndexRef(
                "CSI", "931002", "任何名称", "https://csi.test", "CSINDEX_OFFICIAL_CATALOG",
                eligibility_status="out_of_scope", eligibility_reason="official fixed-income asset class",
            )
            discovered = [in_scope, unknown, out_of_scope]
            calls = []

            def worker(index, _allow_secondary):
                calls.append(index.code)
                return FetchResult(index, "ok")

            with (
                patch("a_share_index_pit.collector.load_catalog_refs", return_value=[]),
                patch("a_share_index_pit.collector.discover_indexes", return_value=(discovered, [])),
                patch("a_share_index_pit.collector._worker", side_effect=worker),
            ):
                summary = collect(tmp, workers=1)

            self.assertCountEqual(calls, ["931001", "CN6010"])
            self.assertEqual(summary["indexes"], 2)
            self.assertEqual(summary["successful"], 2)
            self.assertEqual(summary["failed"], 0)
            self.assertEqual(summary["out_of_scope_skipped"], 1)
            with (Path(tmp) / "index_catalog.csv").open(encoding="utf-8", newline="") as f:
                catalog = {row["index_code"]: row for row in csv.DictReader(f)}
            self.assertEqual(set(catalog), {"931001", "CN6010", "931002"})
            self.assertEqual(catalog["931002"]["eligibility_status"], "out_of_scope")
            with (Path(tmp) / "collection_runs.csv").open(encoding="utf-8", newline="") as f:
                run = next(csv.DictReader(f))
            self.assertEqual(run["indexes"], "2")
            self.assertEqual(run["out_of_scope_skipped"], "1")

    def test_partial_catalog_merges_cached_entries_only_for_failed_source(self):
        cached_cni = IndexRef("CNI", "980001", "湾创100", "https://cni.test", "CNI_OFFICIAL_CATALOG")
        cached_csi = IndexRef("CSI", "000300", "旧沪深300名称", "https://csi.test", "CSINDEX_OFFICIAL_CATALOG")
        discovered_csi = IndexRef("CSI", "000300", "沪深300", "https://csi.test", "CSINDEX_OFFICIAL_CATALOG")
        discovered_other = IndexRef("CSI", "000905", "中证500", "https://csi.test", "CSINDEX_OFFICIAL_CATALOG")

        merged = _merge_incomplete_catalog(
            [discovered_csi, discovered_other],
            [cached_cni, cached_csi],
            [{"catalog": "CNI", "status": "catalog_fetch_failed", "message": "timeout"}],
        )

        self.assertEqual({(ref.provider, ref.code) for ref in merged}, {
            ("CNI", "980001"), ("CSI", "000300"), ("CSI", "000905"),
        })
        self.assertEqual(next(ref for ref in merged if ref.code == "000300").name, "沪深300")

    def test_all_fetch_failures_are_persisted_before_collection_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            ref = IndexRef("CNI", "980001", "湾创100", "https://cni.test", "CNI_OFFICIAL_CATALOG")
            directory_error = {
                "catalog": "CSINDEX",
                "status": "catalog_fetch_failed",
                "message": "CSI official catalog series 1 failed: timeout",
            }
            fetch_failure = FetchResult(ref, "fetch_failed", message="primary=HTTP 503; secondary=timeout")
            with (
                patch("a_share_index_pit.collector.load_catalog_refs", return_value=[]),
                patch("a_share_index_pit.collector.discover_indexes", return_value=([ref], [directory_error])),
                patch("a_share_index_pit.collector._worker", return_value=fetch_failure),
            ):
                with self.assertRaisesRegex(RuntimeError, "diagnostics saved"):
                    collect(tmp, workers=1, allow_secondary=False)

            root = Path(tmp)
            with (root / "observations.csv").open(encoding="utf-8", newline="") as f:
                observations = list(csv.DictReader(f))
            self.assertEqual(observations[0]["source_status"], "fetch_failed")
            self.assertIn("primary=HTTP 503", observations[0]["note"])

            with (root / "catalog_errors.csv").open(encoding="utf-8", newline="") as f:
                errors = list(csv.DictReader(f))
            self.assertEqual(errors[0]["catalog"], "CSINDEX")
            self.assertIn("series 1", errors[0]["message"])

            with (root / "collection_runs.csv").open(encoding="utf-8", newline="") as f:
                run = next(csv.DictReader(f))
            self.assertEqual(run["status"], "failed_all_fetches")
            self.assertEqual(run["successful"], "0")
            self.assertEqual(run["failed"], "1")


if __name__ == "__main__":
    unittest.main()
