from __future__ import annotations

import argparse
import concurrent.futures
import json
import sys
from datetime import datetime, timezone

from .models import FetchResult, IndexRef
from .sources import discover_indexes, fetch_index, make_session
from .store import load_catalog_refs, persist_results


def _worker(index: IndexRef, allow_secondary: bool):
    # A per-worker session avoids sharing mutable requests state across threads.
    session = make_session()
    return fetch_index(session, index, allow_secondary=allow_secondary)


def _merge_incomplete_catalog(
    discovered: list[IndexRef],
    previous_complete: list[IndexRef],
    catalog_errors: list[dict[str, str]],
) -> list[IndexRef]:
    """Keep cached candidates only for sources unavailable in this discovery run."""
    failed_catalogs = {row.get("catalog", "") for row in catalog_errors}
    preserved_sources: set[str] = set()
    if "CNI" in failed_catalogs:
        preserved_sources.update({"CNI", "CNI_OFFICIAL_CATALOG"})
    if "CSINDEX" in failed_catalogs:
        preserved_sources.add("CSINDEX_OFFICIAL_CATALOG")
    if "JOINQUANT_FALLBACK" in failed_catalogs:
        preserved_sources.update({"JOINQUANT_CATALOG", "SEED"})

    refs = {(ref.provider, ref.code): ref for ref in discovered}
    for ref in previous_complete:
        if ref.source_provider in preserved_sources:
            refs.setdefault((ref.provider, ref.code), ref)
    return sorted(refs.values(), key=lambda item: (item.provider, item.code))


def collect(data_dir: str, limit: int | None = None, workers: int = 4,
            allow_secondary: bool = True, dry_run: bool = False) -> dict[str, int]:
    if limit is not None and limit < 1:
        raise ValueError("limit must be a positive integer")

    previous_catalog = load_catalog_refs(data_dir)
    discovered_refs, catalog_errors = discover_indexes(make_session())
    catalog_complete = bool(discovered_refs) and not catalog_errors
    refs = _merge_incomplete_catalog(discovered_refs, previous_catalog, catalog_errors)
    catalog_refs = discovered_refs
    if limit is not None:
        refs = refs[:limit]

    results: list[FetchResult] = []
    # Conservative concurrency to reduce load on index-provider websites.
    if refs:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(workers, 8))) as pool:
            futures = {pool.submit(_worker, index, allow_secondary): index for index in refs}
            for future in concurrent.futures.as_completed(futures):
                index = futures[future]
                try:
                    results.append(future.result())
                except Exception as exc:
                    results.append(FetchResult(index, "fetch_failed", message=str(exc)[:500]))

    if dry_run:
        summary = {
            "indexes": len(refs),
            "successful": sum(result.status.startswith("ok") for result in results),
            "failed": sum(not result.status.startswith("ok") for result in results),
            "catalog_errors": len(catalog_errors),
            "catalog_complete": catalog_complete,
            "new_observations": 0,
            "new_events": 0,
            "dry_run": True,
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return summary

    observed_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    run_id = observed_at.replace(":", "").replace("-", "")
    successful = sum(result.status.startswith("ok") for result in results)
    failed = len(results) - successful

    if not refs:
        run_status = "failed_no_candidates"
        run_message = "No current or cached index candidates; catalog errors are recorded separately."
    elif successful == 0:
        run_status = "failed_all_fetches"
        run_message = f"All {len(refs)} index fetches failed."
    elif catalog_errors:
        run_status = "partial_catalog"
        run_message = "Unavailable catalog sources: " + ", ".join(sorted({e.get("catalog", "unknown") for e in catalog_errors}))
    elif failed:
        run_status = "partial_fetches"
        run_message = f"{failed} of {len(refs)} index fetches failed."
    else:
        run_status = "completed"
        run_message = ""

    summary = persist_results(
        data_dir,
        refs,
        results,
        observed_at,
        run_id,
        catalog_errors,
        catalog_complete=catalog_complete,
        catalog_refs=catalog_refs,
        run_status=run_status,
        run_message=run_message,
    )
    summary["catalog_complete"] = int(catalog_complete)
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if not refs:
        diagnostics = ["collection_runs.csv"]
        if catalog_errors:
            diagnostics.append("catalog_errors.csv")
        raise RuntimeError(
            f"no index candidates discovered; diagnostics saved under {data_dir}/" + ", ".join(diagnostics)
        )
    if successful == 0:
        diagnostics = ["observations.csv", "collection_runs.csv"]
        if catalog_errors:
            diagnostics.append("catalog_errors.csv")
        raise RuntimeError(
            f"all {len(refs)} index fetches failed; diagnostics saved under {data_dir}/" + ", ".join(diagnostics)
        )
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect A-share index PIT observations")
    parser.add_argument("--data-dir", default="./data", help="private data repository directory")
    parser.add_argument("--limit", type=int, default=None, help="limit index candidates for smoke tests")
    parser.add_argument("--workers", type=int, default=4, help="concurrent source requests (max 8)")
    parser.add_argument("--no-secondary", action="store_true", help="disable Eastmoney secondary fallback")
    parser.add_argument("--dry-run", action="store_true", help="run a smoke test without writing files")
    args = parser.parse_args(argv)
    try:
        collect(args.data_dir, args.limit, args.workers, not args.no_secondary, args.dry_run)
        return 0
    except Exception as exc:
        print(f"collection failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
