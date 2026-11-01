from __future__ import annotations

import argparse
import concurrent.futures
import json
import sys
from datetime import datetime, timezone

from .models import FetchResult
from .sources import discover_indexes, fetch_index, make_session
from .store import persist_results


def _worker(index, allow_secondary: bool):
    # A per-worker session avoids sharing mutable requests state across threads.
    session = make_session()
    return fetch_index(session, index, allow_secondary=allow_secondary)


def collect(data_dir: str, limit: int | None = None, workers: int = 4,
            allow_secondary: bool = True, dry_run: bool = False) -> dict[str, int]:
    session = make_session()
    refs, catalog_errors = discover_indexes(session)
    if limit is not None:
        refs = refs[:limit]
    if not refs:
        raise RuntimeError("no index candidates discovered; refusing to write an empty run")

    results = []
    # Conservative concurrency to reduce load on index-provider websites.
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
            "new_observations": 0,
            "new_events": 0,
            "dry_run": True,
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return summary

    observed_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    run_id = observed_at.replace(":", "").replace("-", "")
    summary = persist_results(data_dir, refs, results, observed_at, run_id, catalog_errors)
    summary["catalog_errors"] = len(catalog_errors)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary["successful"] == 0:
        raise RuntimeError("all index fetches failed; inspect catalog_errors.csv and observations.csv")
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
