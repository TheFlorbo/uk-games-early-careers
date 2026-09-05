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
    """Confirmed first, then newest, then games before adjacent."""
    return (0 if rec.get("tier") == "confirmed" else 1,
            rec.get("days_open", 999),
            0 if rec.get("company_type") == "games" else 1,
            rec.get("company", ""),
            rec.get("title", ""))


def dedupe(records: list[dict]) -> list[dict]:
    """Collapse the same role advertised in several cities into one row.

    Starling Bank posts identical listings for London, Manchester and
    Southampton; before this, 59 rows contained only 43 distinct roles and one
    employer filled almost half the page.

    Runs AFTER ageing so each posting is still tracked individually in state --
    the merged row reports the oldest first-seen date, because that is when the
    role actually opened.
    """
    groups: dict[tuple[str, str], list[dict]] = {}
    for r in records:
        key = (r.get("company", ""), " ".join(r.get("title", "").lower().split()))
        groups.setdefault(key, []).append(r)

    merged = []
    for group in groups.values():
        group.sort(key=lambda r: r["uid"])          # deterministic canonical row
        head = dict(group[0])
        locations = sorted({r.get("location", "") for r in group if r.get("location")})
        head["location"] = " · ".join(locations)
        head["location_count"] = len(locations)
        head["days_open"] = max(r.get("days_open", 0) for r in group)
        head["repost_count"] = max(r.get("repost_count", 0) for r in group)
        head["is_new"] = all(r.get("is_new") for r in group)
        if any(r.get("tier") == "confirmed" for r in group):
            head["tier"] = "confirmed"
            head["level_reason"] = next(r["level_reason"] for r in group
                                        if r.get("tier") == "confirmed")
        merged.append(head)
    return merged


def probe(companies: dict) -> int:
    """Validate every configured slug. Exits non-zero if any are dead.

    Greenhouse, Lever, Ashby and Workable 404 on an unknown slug, so a result
    of 0 there means a real board with nothing open right now -- keep it.
    SmartRecruiters instead returns an EMPTY LIST for a company it doesn't
    recognise, so 0 there is ambiguous and gets flagged rather than passed.
    """
    dead = ambiguous = 0
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
            except Exception as exc:                        # noqa: BLE001
                print(f"  XX  {ats:16} {e['slug']:24} {type(exc).__name__}: {exc}"[:110])
                dead += 1
                continue
            if n == 0 and ats == "smartrecruiters":
                print(f"  ??  {ats:16} {e['slug']:24}    0 jobs  "
                      f"(unverifiable - SmartRecruiters returns empty for bad "
                      f"slugs too; confirm at jobs.smartrecruiters.com/{e['slug']})")
                ambiguous += 1
            else:
                print(f"  OK  {ats:16} {e['slug']:24} {n:4d} jobs")

    print(f"\n{dead} dead entr{'y' if dead == 1 else 'ies'} - remove them from companies.yml")
    if ambiguous:
        print(f"{ambiguous} unverifiable - check by hand before trusting")
    return dead


# --------------------------------------------------------------------------
# Slug discovery
# --------------------------------------------------------------------------

_SUFFIXES = ("games", "studios", "studio", "interactive", "entertainment",
             "software", "group", "ltd", "limited", "uk")


def slug_variants(name: str) -> list[str]:
    """Plausible ATS slugs for a company name, commonest spellings first."""
    import re
    base = name.lower().strip()
    compact = re.sub(r"[^a-z0-9]", "", base)
    hyphen = re.sub(r"[^a-z0-9]+", "-", base).strip("-")

    out = {compact, hyphen}
    for stem in (compact, hyphen):
        sep = "-" if "-" in stem or stem == hyphen else ""
        for suf in ("games", "studios", "studio"):
            out.add(f"{stem}{sep}{suf}")
    # Also try dropping a suffix the name already has.
    for suf in _SUFFIXES:
        if compact.endswith(suf) and len(compact) > len(suf) + 2:
            out.add(compact[: -len(suf)])
            out.add(hyphen.rsplit("-", 1)[0] if "-" in hyphen else hyphen)
    return sorted(x for x in out if len(x) > 2)


def find(name: str) -> int:
    """Hunt for a company's job board across every ATS we support.

    Tries each plausible slug against each ATS. Used when adding a company:
        python scan.py --find "Splash Damage"
    """
    import concurrent.futures as cf

    variants = slug_variants(name)
    print(f"Trying {len(variants)} slug(s) x {len(ADAPTERS)} ATS for {name!r}:")
    print("  " + ", ".join(variants) + "\n")

    def attempt(pair):
        ats, slug = pair
        try:
            return ats, slug, len(ADAPTERS[ats](slug, name, "games")), None
        except Exception as exc:                            # noqa: BLE001
            return ats, slug, -1, type(exc).__name__

    pairs = [(a, s) for a in ADAPTERS for s in variants]
    hits = 0
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        for ats, slug, n, err in ex.map(attempt, pairs):
            if n < 0:
                continue                                    # 404 = not this one
            if n == 0 and ats == "smartrecruiters":
                continue                                    # meaningless there
            hits += 1
            print(f"  FOUND  {ats:16} {slug:28} {n:4d} jobs")
            print(f"         - {{ slug: {slug}, name: \"{name}\", type: games }}")

    if not hits:
        print("  No board found. The company may host its own careers page,\n"
              "  or use an ATS this tool doesn't support (Workday, Teamtailor,\n"
              "  Recruitee, Personio, SuccessFactors are the common others).")
    return hits


def load_fixtures(path: Path) -> tuple[list[Job], list[dict]]:
    """Offline mode: build Job records from saved sample payloads."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    jobs = [Job(**j) for j in raw["jobs"]]
    return jobs, raw["health"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--find", metavar="COMPANY",
                    help='hunt for a company\'s job board, e.g. --find "Splash Damage"')
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--offline", metavar="FIXTURE", nargs="?",
                    const="tests/fixtures/sample.json")
    ap.add_argument("--config", default="config.yml")
    ap.add_argument("--companies", default="companies.yml")
    args = ap.parse_args()

    cfg = load_yaml(args.config)
    companies = load_yaml(args.companies)

    if args.find:
        return 0 if find(args.find) else 1

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
    before_dedupe = len(records)
    records = dedupe(records)
    records.sort(key=sort_key)
    records = records[: cfg["site"]["max_listed"]]

    confirmed = sum(1 for r in records if r.get("tier") == "confirmed")
    print(f"fetched {len(jobs)} postings from {len(health)} boards "
          f"({len(healthy)} healthy, {len(failed)} failed)")
    print(f"after filtering: {before_dedupe} matches -> {len(records)} distinct roles")
    print(f"  {confirmed} confirmed entry level, "
          f"{len(records) - confirmed} possible")
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
