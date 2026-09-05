"""ATS adapters.

Each adapter hits one applicant-tracking system's PUBLIC job board endpoint --
the same data the company publishes on its own careers page -- and normalises
it into a common Job record. No API keys, no authentication, no scraping of
rendered HTML.

Adding a new ATS means writing one function that returns list[Job] and
registering it in ADAPTERS. Nothing else in the codebase needs to change.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone

import requests

USER_AGENT = "uk-games-early-careers/1.0 (+https://github.com/)"
TIMEOUT = 20


@dataclass
class Job:
    """One normalised job posting."""
    uid: str                 # stable across runs: "{ats}:{slug}:{native_id}"
    title: str
    company: str
    company_type: str        # "games" | "adjacent"
    location: str
    url: str
    source: str              # which ATS it came from
    description: str = ""    # plain text, used for experience detection
    posted_at: str | None = None   # ISO date if the ATS tells us, else None

    def to_dict(self) -> dict:
        return asdict(self)


class SourceError(Exception):
    """Raised when one company's board can't be read. Never fatal."""


def _get(url: str) -> dict | list:
    r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t\r\f\v]+")


def strip_html(raw: str | None) -> str:
    """HTML -> plain text. Good enough for keyword and regex matching."""
    if not raw:
        return ""
    text = html.unescape(raw)
    text = re.sub(r"<(br|/p|/li|/div|/h\d)[^>]*>", "\n", text, flags=re.I)
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = _WS_RE.sub(" ", text)
    return "\n".join(line.strip() for line in text.split("\n")).strip()


def _iso(value) -> str | None:
    """Normalise assorted ATS date formats to an ISO date string."""
    if not value:
        return None
    try:
        if isinstance(value, (int, float)):          # Lever: epoch millis
            secs = value / 1000 if value > 1e11 else value
            return datetime.fromtimestamp(secs, tz=timezone.utc).date().isoformat()
        text = str(value).strip().replace("Z", "+00:00")
        return datetime.fromisoformat(text).date().isoformat()
    except Exception:
        return str(value)[:10] or None


# --------------------------------------------------------------------------
# Adapters
# --------------------------------------------------------------------------

def greenhouse(slug: str, name: str, ctype: str) -> list[Job]:
    data = _get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true")
    jobs = []
    for j in data.get("jobs", []):
        jobs.append(Job(
            uid=f"greenhouse:{slug}:{j.get('id')}",
            title=(j.get("title") or "").strip(),
            company=name,
            company_type=ctype,
            location=((j.get("location") or {}).get("name") or "").strip(),
            url=j.get("absolute_url") or "",
            source="greenhouse",
            description=strip_html(j.get("content")),
            posted_at=_iso(j.get("updated_at")),
        ))
    return jobs


def lever(slug: str, name: str, ctype: str) -> list[Job]:
    data = _get(f"https://api.lever.co/v0/postings/{slug}?mode=json")
    jobs = []
    for j in data if isinstance(data, list) else []:
        cats = j.get("categories") or {}
        # Lever splits requirements into `lists`; include them so the
        # years-of-experience detector can see them.
        extra = " ".join(strip_html(b.get("content", "")) for b in (j.get("lists") or []))
        body = (j.get("descriptionPlain") or strip_html(j.get("description")) or "")
        jobs.append(Job(
            uid=f"lever:{slug}:{j.get('id')}",
            title=(j.get("text") or "").strip(),
            company=name,
            company_type=ctype,
            location=(cats.get("location") or "").strip(),
            url=j.get("hostedUrl") or j.get("applyUrl") or "",
            source="lever",
            description=f"{body}\n{extra}".strip(),
            posted_at=_iso(j.get("createdAt")),
        ))
    return jobs


def ashby(slug: str, name: str, ctype: str) -> list[Job]:
    data = _get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
    jobs = []
    for j in data.get("jobs", []):
        if j.get("isListed") is False:
            continue
        jobs.append(Job(
            uid=f"ashby:{slug}:{j.get('id')}",
            title=(j.get("title") or "").strip(),
            company=name,
            company_type=ctype,
            location=(j.get("location") or "").strip(),
            url=j.get("jobUrl") or j.get("applyUrl") or "",
            source="ashby",
            description=j.get("descriptionPlain") or strip_html(j.get("descriptionHtml")),
            posted_at=_iso(j.get("publishedAt")),
        ))
    return jobs


def smartrecruiters(slug: str, name: str, ctype: str) -> list[Job]:
    """SmartRecruiters paginates and omits descriptions from the list endpoint.

    We deliberately do NOT fetch each posting's detail page -- that would be one
    request per job. Instead we lean on the `experienceLevel` field the list
    endpoint already gives us, which is more reliable than parsing prose anyway.
    """
    jobs, offset = [], 0
    while True:
        page = _get(
            f"https://api.smartrecruiters.com/v1/companies/{slug}/postings"
            f"?limit=100&offset={offset}"
        )
        content = page.get("content", []) or []
        for j in content:
            loc = j.get("location") or {}
            where = ", ".join(x for x in [loc.get("city"), loc.get("region"),
                                          loc.get("country")] if x)
            level = ((j.get("experienceLevel") or {}).get("label") or "")
            jobs.append(Job(
                uid=f"smartrecruiters:{slug}:{j.get('id')}",
                title=(j.get("name") or "").strip(),
                company=name,
                company_type=ctype,
                location=where.strip(),
                url=f"https://jobs.smartrecruiters.com/{slug}/{j.get('id')}",
                source="smartrecruiters",
                # Surfacing the structured level lets the classifier use it.
                description=f"Experience level: {level}",
                posted_at=_iso(j.get("releasedDate")),
            ))
        offset += 100
        if offset >= page.get("totalFound", 0) or not content:
            break
    return jobs


def workable(slug: str, name: str, ctype: str) -> list[Job]:
    data = _get(f"https://apply.workable.com/api/v1/widget/accounts/{slug}?details=true")
    jobs = []
    for j in data.get("jobs", []):
        where = ", ".join(x for x in [j.get("city"), j.get("state"),
                                      j.get("country")] if x)
        body = " ".join(strip_html(j.get(k)) for k in
                        ("description", "requirements") if j.get(k))
        jobs.append(Job(
            uid=f"workable:{slug}:{j.get('shortcode') or j.get('id')}",
            title=(j.get("title") or "").strip(),
            company=name,
            company_type=ctype,
            location=where.strip(),
            url=j.get("url") or j.get("application_url") or "",
            source="workable",
            description=f"{body} {j.get('experience') or ''}".strip(),
            posted_at=_iso(j.get("published_on") or j.get("created_at")),
        ))
    return jobs


ADAPTERS = {
    "greenhouse": greenhouse,
    "lever": lever,
    "ashby": ashby,
    "smartrecruiters": smartrecruiters,
    "workable": workable,
}


def fetch_all(companies: dict) -> tuple[list[Job], list[dict]]:
    """Fetch every configured board.

    One dead board must never kill the run, so each company is wrapped
    individually and its outcome recorded. The health report is rendered on the
    page so readers (and you) can see when a source has silently stopped
    working -- the most common way a feed like this rots without anyone noticing.
    """
    all_jobs: list[Job] = []
    health: list[dict] = []

    for ats, entries in (companies or {}).items():
        adapter = ADAPTERS.get(ats)
        if adapter is None:
            health.append({"ats": ats, "slug": "-", "ok": False,
                           "count": 0, "error": "no adapter registered"})
            continue
        for entry in entries or []:
            slug = entry.get("slug")
            name = entry.get("name") or slug
            ctype = entry.get("type") or "adjacent"
            try:
                found = adapter(slug, name, ctype)
                all_jobs.extend(found)
                health.append({"ats": ats, "slug": slug, "name": name,
                               "ok": True, "count": len(found), "error": ""})
            except Exception as exc:                       # noqa: BLE001
                health.append({"ats": ats, "slug": slug, "name": name,
                               "ok": False, "count": 0,
                               "error": f"{type(exc).__name__}: {exc}"[:160]})
    return all_jobs, health
