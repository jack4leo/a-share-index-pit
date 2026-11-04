from __future__ import annotations

import csv
import gzip
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from .classification import classify_cni
from .models import FetchResult, IndexRef, Snapshot
from .sources import is_a_share_equity_code

PARSER_VERSION = "0.1.0"
CATALOG_FIELDS = [
    "provider", "index_code", "index_name", "catalog_url", "source_provider", "candidate_scope", "note",
    "source_classification", "primary_category", "universe_scope_tags", "geography_region_tags",
    "style_factor_tags", "strategy_tags",
]
OBSERVATION_FIELDS = [
    "run_id", "observed_at", "provider", "index_code", "index_name", "source_status",
    "source_provider", "source_asof", "member_count", "membership_hash", "source_sha256",
    "source_url", "valid_boundary", "confidence", "note", "parser_version",
]
EVENT_FIELDS = [
    "event_id", "provider", "index_code", "index_name", "effective_date", "security_code",
    "action", "observed_at", "source_provider", "source_url", "source_sha256", "state_hash",
    "valid_boundary", "confidence", "revision_of", "parser_version",
]
RUN_DIAGNOSTIC_FIELDS = [
    "run_id", "observed_at", "indexes", "successful", "failed", "catalog_errors",
    "catalog_complete", "status", "message",
]


def _read_csv(path: Path, fields: list[str]) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    if path.name.endswith(".gz"):
        source = gzip.open(path, "rt", encoding="utf-8-sig", newline="")
    else:
        source = path.open("r", encoding="utf-8-sig", newline="")
    with source as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return []
        return [{field: row.get(field, "") or "" for field in fields} for row in reader]


def _catalog_tags(value: str, *, empty_is_unknown: bool = True) -> tuple[str, ...]:
    if not value:
        return ("unknown",)
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return ("unknown",)
    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        return ("unknown",)
    if not parsed and empty_is_unknown:
        return ("unknown",)
    return tuple(parsed)


def load_catalog_refs(data_dir: str | Path) -> list[IndexRef]:
    """Load the last persisted complete candidate catalog, if present."""
    rows = _read_csv(Path(data_dir) / "index_catalog.csv", CATALOG_FIELDS)
    refs = []
    for row in rows:
        source_classification = row["source_classification"]
        primary_category = row["primary_category"] or "unknown"
        universe_scope_tags = _catalog_tags(row["universe_scope_tags"])
        geography_region_tags = _catalog_tags(row["geography_region_tags"])
        style_factor_tags = _catalog_tags(row["style_factor_tags"], empty_is_unknown=False) if row["style_factor_tags"] else ()
        strategy_tags = _catalog_tags(row["strategy_tags"], empty_is_unknown=False) if row["strategy_tags"] else ()

        # Older catalogs kept CNI's official indextype only in free-text note.
        # Recover that explicit native value without attempting any name-based inference.
        if not source_classification and row["provider"] == "CNI" and row["source_provider"] == "CNI_OFFICIAL_CATALOG":
            for part in row["note"].split(";"):
                if part.strip().startswith("index_type="):
                    legacy_type = part.strip().split("=", 1)[1]
                    if not legacy_type or legacy_type == "unknown":
                        break
                    migrated = classify_cni(legacy_type)
                    source_classification = migrated["source_classification"]
                    primary_category = migrated["primary_category"]
                    universe_scope_tags = migrated["universe_scope_tags"]
                    geography_region_tags = migrated["geography_region_tags"]
                    style_factor_tags = migrated["style_factor_tags"]
                    strategy_tags = migrated["strategy_tags"]
                    break

        refs.append(IndexRef(
            provider=row["provider"],
            code=row["index_code"],
            name=row["index_name"],
            catalog_url=row["catalog_url"],
            source_provider=row["source_provider"],
            note=row["note"],
            source_classification=source_classification,
            primary_category=primary_category,
            universe_scope_tags=universe_scope_tags,
            geography_region_tags=geography_region_tags,
            style_factor_tags=style_factor_tags,
            strategy_tags=strategy_tags,
        ))
    return [ref for ref in refs if ref.provider and ref.code and ref.name]


def _write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def _append_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.name.endswith(".gz"):
        exists = False
        if path.exists() and path.stat().st_size > 0:
            with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as prior:
                exists = bool(prior.readline())
        destination = gzip.open(path, "at", encoding="utf-8", newline="")
    else:
        exists = path.exists() and path.stat().st_size > 0
        destination = path.open("a", encoding="utf-8", newline="")
    with destination as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        if not exists:
            writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def _state_hash(codes: set[str]) -> str:
    raw = "\n".join(sorted(codes)).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _event_id(provider: str, code: str, effective_date: str, action: str, security_code: str, state_hash: str) -> str:
    raw = "|".join((provider, code, effective_date, action, security_code, state_hash)).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _safe_filename(value: str) -> str:
    return "".join(char if char.isalnum() or char in "-_" else "_" for char in value)


def _write_normalized_history(data_dir: Path, result: FetchResult) -> None:
    if not result.snapshots:
        return
    path = data_dir / "source_history" / result.index.provider / f"{_safe_filename(result.index.code)}.csv.gz"
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for snap in result.snapshots:
        for member in snap.members:
            rows.append({
                "effective_date": snap.source_date,
                "security_code": member.get("security_code", ""),
                "security_name": member.get("security_name", ""),
                "weight_source_value": member.get("weight_source_value", ""),
                "source_provider": snap.source_provider,
                "source_url": snap.source_url,
                "source_sha256": snap.source_sha256,
                "confidence": snap.confidence,
                "valid_boundary": snap.valid_boundary,
            })
    frame = pd.DataFrame(rows)
    if frame.empty:
        return
    frame = frame.sort_values(["effective_date", "security_code"])
    csv_bytes = frame.to_csv(index=False).encode("utf-8")
    # Fix gzip mtime so an unchanged source file does not create a new Git diff daily.
    compressed = gzip.compress(csv_bytes, compresslevel=9, mtime=0)
    path.write_bytes(compressed)


def _filtered_a_share_members(snapshot: Snapshot) -> tuple[set[str], bool]:
    raw_codes = {str(member.get("security_code", "")).strip() for member in snapshot.members if member.get("security_code")}
    a_share_codes = {code for code in raw_codes if is_a_share_equity_code(code)}
    all_a_share = bool(raw_codes) and len(a_share_codes) == len(raw_codes)
    return a_share_codes, all_a_share


def _event_rows(
    index: IndexRef,
    snapshot: Snapshot,
    previous: set[str] | None,
    observed_at: str,
    *,
    correction: bool = False,
) -> tuple[list[dict[str, Any]], set[str], str]:
    current, all_a = _filtered_a_share_members(snapshot)
    digest = _state_hash(current)
    if not current:
        return [], current, "no_a_share_members"
    if previous is None:
        changes = [("BASELINE", code) for code in sorted(current)]
    else:
        changes = [("ADD", code) for code in sorted(current - previous)]
        changes += [("REMOVE", code) for code in sorted(previous - current)]
    result = []
    if correction:
        confidence = "same_date_source_correction_review_required"
    elif previous is None and snapshot.source_provider == "CNI_OFFICIAL_SAMPLE_FILE":
        confidence = "history_start_unverified"
    else:
        confidence = snapshot.confidence
    for action, code in changes:
        eid = _event_id(index.provider, index.code, snapshot.source_date, action, code, digest)
        result.append({
            "event_id": eid,
            "provider": index.provider,
            "index_code": index.code,
            "index_name": index.name,
            "effective_date": snapshot.source_date,
            "security_code": code,
            "action": action,
            "observed_at": observed_at,
            "source_provider": snapshot.source_provider,
            "source_url": snapshot.source_url,
            "source_sha256": snapshot.source_sha256,
            "state_hash": digest,
            "valid_boundary": snapshot.valid_boundary,
            "confidence": confidence,
            "revision_of": "" if not correction else "prior_source_state_same_effective_date",
            "parser_version": PARSER_VERSION,
        })
    return result, current, "ok"


def persist_results(
    data_dir: str | Path,
    refs: list[IndexRef],
    results: list[FetchResult],
    observed_at: str,
    run_id: str,
    catalog_errors: list[dict[str, str]] | None = None,
    *,
    catalog_complete: bool = True,
    catalog_refs: list[IndexRef] | None = None,
    run_status: str = "completed",
    run_message: str = "",
) -> dict[str, int]:
    root = Path(data_dir)
    root.mkdir(parents=True, exist_ok=True)

    catalog_rows = [{
        "provider": ref.provider, "index_code": ref.code, "index_name": ref.name,
        "catalog_url": ref.catalog_url, "source_provider": ref.source_provider,
        "candidate_scope": "candidate_pending_sample_validation", "note": ref.note,
        "source_classification": ref.source_classification,
        "primary_category": ref.primary_category,
        "universe_scope_tags": json.dumps(ref.universe_scope_tags, ensure_ascii=False),
        "geography_region_tags": json.dumps(ref.geography_region_tags, ensure_ascii=False),
        "style_factor_tags": json.dumps(ref.style_factor_tags, ensure_ascii=False),
        "strategy_tags": json.dumps(ref.strategy_tags, ensure_ascii=False),
    } for ref in (catalog_refs if catalog_refs is not None else refs)]
    if catalog_complete:
        _write_csv(root / "index_catalog.csv", CATALOG_FIELDS, catalog_rows)

    latest_path = root / "latest_state.json"
    latest_state = json.loads(latest_path.read_text(encoding="utf-8")) if latest_path.exists() else {}
    event_csv = root / "membership_events.csv"
    event_gzip = root / "membership_events.csv.gz"
    prior_events = [
        row
        for path in (event_csv, event_gzip)
        for row in _read_csv(path, EVENT_FIELDS)
    ]
    event_path = event_gzip if event_gzip.exists() else event_csv
    known_event_ids = {row["event_id"] for row in prior_events}
    observations = _read_csv(root / "observations.csv", OBSERVATION_FIELDS)
    known_observation_keys = {(row["run_id"], row["provider"], row["index_code"]) for row in observations}
    new_events: list[dict[str, Any]] = []
    new_observations: list[dict[str, Any]] = []
    success_count = failed_count = 0

    for result in results:
        if result.status.startswith("ok"):
            success_count += 1
        else:
            failed_count += 1
        snapshots = sorted(result.snapshots, key=lambda item: item.source_date)
        latest_snapshot = snapshots[-1] if snapshots else None
        member_codes, all_a = _filtered_a_share_members(latest_snapshot) if latest_snapshot else (set(), False)
        membership_hash = _state_hash(member_codes) if member_codes else ""
        observation_status = result.status
        note = result.message
        key = result.index.key
        prior = latest_state.get(key)
        previous_date = prior.get("source_date", "") if prior else ""
        is_stale = bool(
            latest_snapshot
            and latest_snapshot.source_date
            and previous_date
            and latest_snapshot.source_date < previous_date
        )
        if is_stale:
            observation_status = "stale_snapshot"
            note = (note + "; " if note else "") + (
                f"source effective date {latest_snapshot.source_date} is older than "
                f"the last accepted date {previous_date}; state and events were not changed"
            )
        elif latest_snapshot and not latest_snapshot.source_date:
            observation_status = "no_source_date"
            note = (note + "; " if note else "") + "source supplied no usable date; no PIT event emitted"
        elif latest_snapshot and not all_a:
            observation_status = "partial_non_a_members"
            note = (note + "; " if note else "") + "non-A-share identifiers excluded; recognized A-share members are retained as a partial state"

        if latest_snapshot and latest_snapshot.source_date and member_codes and not is_stale:
            if result.index.provider == "CNI" and len(snapshots) > 1:
                # Only replay multiple dated states when the source file actually supplies them.
                previous: set[str] | None = None
                for snapshot in snapshots:
                    if not snapshot.source_date:
                        continue
                    event_rows, current, validation = _event_rows(result.index, snapshot, previous, observed_at)
                    if validation != "ok":
                        continue
                    for row in event_rows:
                        if row["event_id"] not in known_event_ids:
                            new_events.append(row)
                            known_event_ids.add(row["event_id"])
                    previous = current
                if previous is not None:
                    latest_state[key] = {
                        "source_date": snapshots[-1].source_date,
                        "members": sorted(previous),
                        "membership_hash": _state_hash(previous),
                        "source_sha256": latest_snapshot.source_sha256,
                        "observed_at": observed_at,
                        "confidence": "history_start_unverified",
                    }
            else:
                # Single-date CNI and CSI files are observed current states; compare them
                # with the previous daily observation instead of inventing a new baseline.
                previous = set(prior.get("members", [])) if prior else None
                current = member_codes
                if previous_date == latest_snapshot.source_date and previous is not None and previous != current:
                    event_rows, _, validation = _event_rows(result.index, latest_snapshot, previous, observed_at, correction=True)
                    if validation == "ok":
                        for row in event_rows:
                            if row["event_id"] not in known_event_ids:
                                new_events.append(row)
                                known_event_ids.add(row["event_id"])
                    latest_state[key] = {
                        "source_date": latest_snapshot.source_date, "members": sorted(current),
                        "membership_hash": membership_hash, "source_sha256": latest_snapshot.source_sha256,
                        "observed_at": observed_at, "confidence": "review_same_date_revision",
                    }
                elif not previous_date or latest_snapshot.source_date > previous_date:
                    event_rows, _, validation = _event_rows(result.index, latest_snapshot, previous, observed_at)
                    if validation == "ok":
                        for row in event_rows:
                            if row["event_id"] not in known_event_ids:
                                new_events.append(row)
                                known_event_ids.add(row["event_id"])
                    latest_state[key] = {
                        "source_date": latest_snapshot.source_date, "members": sorted(current),
                        "membership_hash": membership_hash, "source_sha256": latest_snapshot.source_sha256,
                        "observed_at": observed_at, "confidence": latest_snapshot.confidence,
                    }
            _write_normalized_history(root, result)

        # Write the observation only after the stale/revision decision so its status
        # matches the state/event handling above and retains this run's source_asof.
        obs_key = (run_id, result.index.provider, result.index.code)
        if obs_key not in known_observation_keys:
            new_observations.append({
                "run_id": run_id,
                "observed_at": observed_at,
                "provider": result.index.provider,
                "index_code": result.index.code,
                "index_name": result.index.name,
                "source_status": observation_status,
                "source_provider": result.source_provider,
                "source_asof": latest_snapshot.source_date if latest_snapshot else "",
                "member_count": len(member_codes),
                "membership_hash": membership_hash,
                "source_sha256": result.source_sha256 or (latest_snapshot.source_sha256 if latest_snapshot else ""),
                "source_url": result.source_url or (latest_snapshot.source_url if latest_snapshot else ""),
                "valid_boundary": latest_snapshot.valid_boundary if latest_snapshot else "",
                "confidence": latest_snapshot.confidence if latest_snapshot else "",
                "note": note,
                "parser_version": PARSER_VERSION,
            })
            known_observation_keys.add(obs_key)

    _append_csv(root / "observations.csv", OBSERVATION_FIELDS, new_observations)
    _append_csv(event_path, EVENT_FIELDS, new_events)
    latest_path.write_text(json.dumps(latest_state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if catalog_errors:
        _append_csv(root / "catalog_errors.csv", ["observed_at", "run_id", "catalog", "status", "message"],
                    [{"observed_at": observed_at, "run_id": run_id, **row} for row in catalog_errors])

    _append_csv(root / "collection_runs.csv", RUN_DIAGNOSTIC_FIELDS, [{
        "run_id": run_id,
        "observed_at": observed_at,
        "indexes": len(refs),
        "successful": success_count,
        "failed": failed_count,
        "catalog_errors": len(catalog_errors or []),
        "catalog_complete": str(bool(catalog_complete)).lower(),
        "status": run_status,
        "message": run_message,
    }])

    return {"indexes": len(refs), "successful": success_count, "failed": failed_count,
            "new_observations": len(new_observations), "new_events": len(new_events),
            "catalog_errors": len(catalog_errors or [])}
