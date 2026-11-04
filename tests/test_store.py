import csv
import gzip
import json
import tempfile
import unittest
from pathlib import Path

from a_share_index_pit.models import FetchResult, IndexRef, Snapshot
from a_share_index_pit.store import load_catalog_refs, persist_results


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

    def test_existing_gzip_event_ledger_is_read_deduplicated_and_appended(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first_snapshot = self._snapshot("2026-10-30", ["600000", "000001"], "hash1")
            first = FetchResult(self.ref, "ok", [first_snapshot], "CSINDEX_OFFICIAL_FILE",
                                first_snapshot.source_url, "hash1")
            persist_results(root, [self.ref], [first], "2026-10-30T08:30:00+00:00", "run1")

            plain_path = root / "membership_events.csv"
            gzip_path = root / "membership_events.csv.gz"
            gzip_path.write_bytes(gzip.compress(plain_path.read_bytes(), mtime=0))
            plain_path.unlink()
            compressed_before = gzip_path.read_bytes()
            (root / "latest_state.json").unlink()

            replay = persist_results(
                root, [self.ref], [first], "2026-10-31T08:30:00+00:00", "run2"
            )
            self.assertEqual(replay["new_events"], 0)
            self.assertEqual(gzip_path.read_bytes(), compressed_before)

            second_snapshot = self._snapshot("2026-11-02", ["600000", "300750"], "hash2")
            second = FetchResult(self.ref, "ok", [second_snapshot], "CSINDEX_OFFICIAL_FILE",
                                 second_snapshot.source_url, "hash2")
            summary = persist_results(
                root, [self.ref], [second], "2026-11-02T08:30:00+00:00", "run3"
            )
            self.assertEqual(summary["new_events"], 2)
            self.assertFalse(plain_path.exists())
            self.assertTrue(gzip_path.read_bytes().startswith(compressed_before))
            with gzip.open(gzip_path, "rt", encoding="utf-8", newline="") as f:
                events = list(csv.DictReader(f))
            self.assertEqual(len(events), 4)
            self.assertEqual(len({row["event_id"] for row in events}), 4)
            actions = {(row["effective_date"], row["security_code"]): row["action"] for row in events}
            self.assertEqual(actions[("2026-11-02", "300750")], "ADD")
            self.assertEqual(actions[("2026-11-02", "000001")], "REMOVE")

    def test_mixed_non_a_share_state_retains_a_share_subset(self):
        with tempfile.TemporaryDirectory() as tmp:
            mixed = self._snapshot("2026-10-30", ["600000", "00700"], "hash1")
            result = FetchResult(self.ref, "ok", [mixed], "CSINDEX_OFFICIAL_FILE", mixed.source_url, "hash1")
            summary = persist_results(Path(tmp), [self.ref], [result], "2026-10-30T08:30:00+00:00", "run1")
            self.assertEqual(summary["new_events"], 1)
            with (Path(tmp) / "observations.csv").open(encoding="utf-8", newline="") as f:
                row = next(csv.DictReader(f))
            self.assertEqual(row["source_status"], "partial_non_a_members")
            with (Path(tmp) / "membership_events.csv").open(encoding="utf-8", newline="") as f:
                events = list(csv.DictReader(f))
            self.assertEqual([(event["security_code"], event["action"]) for event in events], [("600000", "BASELINE")])

    def test_non_a_share_only_state_is_not_emitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = self._snapshot("2026-10-30", ["00700"], "hash1")
            result = FetchResult(self.ref, "ok", [snapshot], "CSINDEX_OFFICIAL_FILE", snapshot.source_url, "hash1")
            summary = persist_results(Path(tmp), [self.ref], [result], "2026-10-30T08:30:00+00:00", "run1")
            self.assertEqual(summary["new_events"], 0)

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


    def test_stale_snapshot_is_recorded_but_does_not_regress_state_or_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = self._snapshot("2026-10-30", ["600000", "000001"], "hash1")
            first = FetchResult(self.ref, "ok", [baseline], "CSINDEX_OFFICIAL_FILE", baseline.source_url, "hash1")
            persist_results(root, [self.ref], [first], "2026-10-30T08:30:00+00:00", "run1")
            events_before = (root / "membership_events.csv").read_bytes()

            stale = self._snapshot("2026-10-29", ["600000", "300750"], "stale-hash")
            second = FetchResult(self.ref, "ok", [stale], "CSINDEX_OFFICIAL_FILE", stale.source_url, "stale-hash")
            persist_results(root, [self.ref], [second], "2026-11-02T08:30:00+00:00", "run2")

            with (root / "observations.csv").open(encoding="utf-8", newline="") as f:
                observations = list(csv.DictReader(f))
            stale_observation = observations[-1]
            self.assertEqual(stale_observation["source_status"], "stale_snapshot")
            self.assertEqual(stale_observation["source_asof"], "2026-10-29")
            self.assertEqual(stale_observation["observed_at"], "2026-11-02T08:30:00+00:00")
            self.assertIn("older than the last accepted date 2026-10-30", stale_observation["note"])
            self.assertEqual((root / "membership_events.csv").read_bytes(), events_before)

            import json
            latest = json.loads((root / "latest_state.json").read_text(encoding="utf-8"))
            self.assertEqual(latest[self.ref.key]["source_date"], "2026-10-30")
            self.assertEqual(set(latest[self.ref.key]["members"]), {"000001", "600000"})

    def test_incomplete_catalog_keeps_last_complete_catalog_and_records_source_error(self):
        from a_share_index_pit.store import load_catalog_refs

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            persist_results(root, [self.ref], [], "2026-11-01T08:30:00+00:00", "run1")
            catalog_path = root / "index_catalog.csv"
            original_catalog = catalog_path.read_bytes()
            newly_discovered = IndexRef("CSI", "000300", "沪深300", "https://example.test", "CSINDEX_OFFICIAL_CATALOG")
            error = {"catalog": "CNI", "status": "catalog_fetch_failed", "message": "CNI endpoint timed out"}

            persist_results(
                root,
                [newly_discovered],
                [],
                "2026-11-02T08:30:00+00:00",
                "run2",
                [error],
                catalog_complete=False,
                catalog_refs=[newly_discovered],
                run_status="partial_catalog",
                run_message="Unavailable catalog sources: CNI",
            )

            self.assertEqual(catalog_path.read_bytes(), original_catalog)
            self.assertEqual([(ref.provider, ref.code) for ref in load_catalog_refs(root)], [(self.ref.provider, self.ref.code)])
            with (root / "catalog_errors.csv").open(encoding="utf-8", newline="") as f:
                errors = list(csv.DictReader(f))
            self.assertEqual(errors[-1]["catalog"], "CNI")
            self.assertEqual(errors[-1]["message"], "CNI endpoint timed out")
            with (root / "collection_runs.csv").open(encoding="utf-8", newline="") as f:
                runs = list(csv.DictReader(f))
            self.assertEqual(runs[-1]["catalog_complete"], "false")
            self.assertEqual(runs[-1]["status"], "partial_catalog")

    def test_catalog_classification_round_trips_as_native_json_and_independent_tags(self):
        with tempfile.TemporaryDirectory() as tmp:
            classified = IndexRef(
                "CSI", "000300", "沪深300", "https://example.test/catalog", "CSINDEX_OFFICIAL_CATALOG",
                source_classification=json.dumps({"indexClassify": "规模", "assetsClassify": "股票"}, ensure_ascii=False),
                primary_category="market_size",
                universe_scope_tags=("equity",),
                geography_region_tags=("china_mainland",),
                style_factor_tags=(),
                strategy_tags=(),
            )
            persist_results(Path(tmp), [classified], [], "2026-11-04T08:00:00+00:00", "run1")

            with (Path(tmp) / "index_catalog.csv").open(encoding="utf-8", newline="") as f:
                row = next(csv.DictReader(f))
            self.assertEqual(json.loads(row["source_classification"])["indexClassify"], "规模")
            self.assertEqual(row["primary_category"], "market_size")
            self.assertEqual(json.loads(row["universe_scope_tags"]), ["equity"])
            self.assertEqual(json.loads(row["geography_region_tags"]), ["china_mainland"])

            loaded = load_catalog_refs(tmp)[0]
            self.assertEqual(loaded.source_classification, classified.source_classification)
            self.assertEqual(loaded.primary_category, "market_size")
            self.assertEqual(loaded.universe_scope_tags, ("equity",))
            self.assertEqual(loaded.geography_region_tags, ("china_mainland",))
            self.assertEqual(loaded.style_factor_tags, ())
            self.assertEqual(loaded.strategy_tags, ())

    def test_legacy_cni_type_is_migrated_but_unrecognized_legacy_csi_class_stays_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "index_catalog.csv"
            with path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=[
                    "provider", "index_code", "index_name", "catalog_url", "source_provider", "candidate_scope", "note",
                ])
                writer.writeheader()
                writer.writerow({
                    "provider": "CNI", "index_code": "399001", "index_name": "深证成指",
                    "catalog_url": "https://example.test", "source_provider": "CNI_OFFICIAL_CATALOG",
                    "note": "official_visible=1; index_type=100; catalog_sample_size=500",
                })
                writer.writerow({
                    "provider": "CSI", "index_code": "000300", "index_name": "沪深300",
                    "catalog_url": "https://example.test", "source_provider": "CSINDEX_OFFICIAL_CATALOG",
                    "note": "series=1; asset_class=股票; region=境内",
                })

            refs = {ref.provider: ref for ref in load_catalog_refs(tmp)}
            self.assertEqual(refs["CNI"].primary_category, "market_size")
            self.assertEqual(json.loads(refs["CNI"].source_classification)["indextype"], "100")
            self.assertEqual(refs["CSI"].primary_category, "unknown")


if __name__ == "__main__":
    unittest.main()
