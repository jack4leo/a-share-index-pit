import csv
import tempfile
import unittest
from pathlib import Path

from a_share_index_pit.models import FetchResult, IndexRef, Snapshot
from a_share_index_pit.store import persist_results


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.ref = IndexRef("CSI_OR_SSE", "000510", "中证A500", "https://example.test/catalog", "CSINDEX")

    def _snapshot(self, day, codes, digest):
        return Snapshot(
            index=self.ref,
            source_date=day,
            members=[{"security_code": code} for code in codes],
            source_provider="CSINDEX_OFFICIAL_FILE",
            source_url="https://example.test/cons.xls",
            source_sha256=digest,
            valid_boundary="unknown",
            confidence="official_current_state",
        )

    def test_baseline_then_add_remove(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = FetchResult(self.ref, "ok", [self._snapshot("2026-10-30", ["600000", "000001"], "hash1")],
                                "CSINDEX_OFFICIAL_FILE", "https://example.test/cons.xls", "hash1")
            summary = persist_results(root, [self.ref], [first], "2026-10-30T08:30:00+00:00", "run1")
            self.assertEqual(summary["new_events"], 2)
            second = FetchResult(self.ref, "ok", [self._snapshot("2026-11-02", ["600000", "300750"], "hash2")],
                                 "CSINDEX_OFFICIAL_FILE", "https://example.test/cons.xls", "hash2")
            summary = persist_results(root, [self.ref], [second], "2026-11-02T08:30:00+00:00", "run2")
            self.assertEqual(summary["new_events"], 2)
            with (root / "membership_events.csv").open(encoding="utf-8", newline="") as f:
                events = list(csv.DictReader(f))
            actions = {(row["effective_date"], row["security_code"]): row["action"] for row in events}
            self.assertEqual(actions[("2026-10-30", "000001")], "BASELINE")
            self.assertEqual(actions[("2026-11-02", "300750")], "ADD")
            self.assertEqual(actions[("2026-11-02", "000001")], "REMOVE")

    def test_mixed_non_a_share_state_is_not_emitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            mixed = self._snapshot("2026-10-30", ["600000", "00700"], "hash1")
            result = FetchResult(self.ref, "ok", [mixed], "CSINDEX_OFFICIAL_FILE", mixed.source_url, "hash1")
            summary = persist_results(Path(tmp), [self.ref], [result], "2026-10-30T08:30:00+00:00", "run1")
            self.assertEqual(summary["new_events"], 0)
            with (Path(tmp) / "observations.csv").open(encoding="utf-8", newline="") as f:
                row = next(csv.DictReader(f))
            self.assertEqual(row["source_status"], "partial_non_a_members")

    def test_cni_daily_snapshot_diffs_previous_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cni_ref = IndexRef("CNI", "399001", "深证成指", "https://example.test/catalog", "CNI")

            def snapshot(day, codes, digest):
                return Snapshot(cni_ref, day, [{"security_code": code} for code in codes],
                                "CNI_OFFICIAL_SAMPLE_FILE", "https://example.test/history.xlsx",
                                digest, "unknown", "official_current_state")

            first_snapshot = snapshot("2026-10-30", ["600000", "000001"], "hash1")
            first = FetchResult(cni_ref, "ok", [first_snapshot], "CNI_OFFICIAL_SAMPLE_FILE",
                                first_snapshot.source_url, "hash1")
            self.assertEqual(persist_results(root, [cni_ref], [first], "2026-10-30T08:30:00+00:00", "run1")["new_events"], 2)

            second_snapshot = snapshot("2026-11-02", ["600000", "300750"], "hash2")
            second = FetchResult(cni_ref, "ok", [second_snapshot], "CNI_OFFICIAL_SAMPLE_FILE",
                                 second_snapshot.source_url, "hash2")
            self.assertEqual(persist_results(root, [cni_ref], [second], "2026-11-02T08:30:00+00:00", "run2")["new_events"], 2)
            with (root / "membership_events.csv").open(encoding="utf-8", newline="") as f:
                events = list(csv.DictReader(f))
            actions = {(row["effective_date"], row["security_code"]): row["action"] for row in events}
            self.assertEqual(actions[("2026-10-30", "000001")], "BASELINE")
            self.assertEqual(actions[("2026-11-02", "300750")], "ADD")
            self.assertEqual(actions[("2026-11-02", "000001")], "REMOVE")

    def test_same_cni_history_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            cni_ref = IndexRef("CNI", "399001", "深证成指", "https://example.test/catalog", "CNI")
            old = Snapshot(cni_ref, "2026-06-15", [{"security_code": "600000"}], "CNI_OFFICIAL_SAMPLE_FILE",
                           "https://example.test/history.xlsx", "hash1", "source_date", "official_file_state")
            new = Snapshot(cni_ref, "2026-12-14", [{"security_code": "600000"}, {"security_code": "300750"}],
                           "CNI_OFFICIAL_SAMPLE_FILE", "https://example.test/history.xlsx", "hash2", "unknown", "official_dated_states")
            result = FetchResult(cni_ref, "ok", [old, new], "CNI_OFFICIAL_SAMPLE_FILE", old.source_url, "fullhash")
            persist_results(Path(tmp), [self.ref], [result], "2026-12-15T08:30:00+00:00", "run1")
            second = persist_results(Path(tmp), [self.ref], [result], "2026-12-16T08:30:00+00:00", "run2")
            self.assertEqual(second["new_events"], 0)


if __name__ == "__main__":
    unittest.main()
