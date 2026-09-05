#!/usr/bin/env python3
"""Entry point.

  python scan.py            fetch, filter, age, render into docs/
  python scan.py --probe    check which company slugs are actually live
  python scan.py --dry-run  run everything but write nothing
  python scan.py --offline  render from tests/fixtures instead of the network
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

import render
import store
from classify import classify
from sources import ADAPTERS, Job, fetch_all


def load_yaml(path: str) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def sort_key(rec: dict):
    """Newest first, then games before adjacent, then alphabetical."""
    return (rec.get("days_open", 999),
            0 if rec.get("company_type") == "games" else 1,
            rec.get("company", ""),
            rec.get("title", ""))


def probe(companies: dict) -> int:
    """Validate every configured slug. Exits non-zero if any are dead."""
    dead = 0
    for ats, entries in (companies or {}).items():
        adapter = ADAPTERS.get(ats)
        if not adapter:
            print(f"  ??  {ats:16} no adapter registered")
            dead += 1
            continue
        for e in entries or []:
            try:
                n = len(adapter(e["slug"], e.get("name", e["slug"]),
                                e.get("type", "adjacent")))
                print(f"  OK  {ats:16} {e['slug']:24} {n:4d} jobs")
            except Exception as exc:                        # noqa: BLE001
                print(f"  XX  {ats:16} {e['slug']:24} {type(exc).__name__}: {exc}"[:110])
                dead += 1
    print(f"\n{dead} dead entr{'y' if dead == 1 else 'ies'} - remove them from companies.yml")
    return dead


def load_fixtures(path: Path) -> tuple[list[Job], list[dict]]:
    """Offline mode: build Job records from saved sample payloads."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    jobs = [Job(**j) for j in raw["jobs"]]
    return jobs, raw["health"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--offline", metavar="FIXTURE", nargs="?",
                    const="tests/fixtures/sample.json")
    ap.add_argument("--config", default="config.yml")
    ap.add_argument("--companies", default="companies.yml")
    args = ap.parse_args()

    cfg = load_yaml(args.config)
    companies = load_yaml(args.companies)

    if args.probe:
        return 1 if probe(companies) else 0

    if args.offline:
        jobs, health = load_fixtures(Path(args.offline))
    else:
        jobs, health = fetch_all(companies)

    healthy = {f"{h['ats']}:{h['slug']}" for h in health if h["ok"]}
    failed = [h for h in health if not h["ok"]]

    records = [r for r in (classify(j, cfg) for j in jobs) if r]

    state = store.load()
    records = store.update(state, records, healthy)

    # Hide anything that has been open longer than we think is useful.
    limit = cfg["site"]["drop_after_days"]
    records = [r for r in records if r["days_open"] <= limit]
    records.sort(key=sort_key)
    records = records[: cfg["site"]["max_listed"]]

    print(f"fetched {len(jobs)} postings from {len(health)} boards "
          f"({len(healthy)} healthy, {len(failed)} failed)")
    print(f"after filtering: {len(records)} UK entry-level roles")
    new = sum(1 for r in records if r.get("is_new"))
    reposted = sum(1 for r in records if r.get("repost_count"))
    print(f"  {new} new since last run, {reposted} previously reposted")
    for h in failed:
        print(f"  FAILED {h['ats']}:{h['slug']} - {h['error']}")

    if args.dry_run:
        print("\n--dry-run: nothing written")
        return 0

    render.write_all(records, health, cfg)
    store.save(store.prune(state, limit))
    print(f"wrote docs/index.html, docs/feed.xml, docs/jobs.json")

    # A run where every single source failed is a broken run, not an empty day.
    if health and not healthy:
        print("ERROR: every source failed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
