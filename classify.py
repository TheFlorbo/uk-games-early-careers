"""Filtering: is this role in the UK, is it relevant, and is it REALLY entry level?

The last question is the one that matters. Every big job board has an
"entry level" filter and every one of them returns roles demanding three years
of experience, because they trust whatever box the employer ticked. We instead
read the posting text and reject anything whose stated requirement is above the
threshold, unless the title is explicitly a grad/intern/junior role.
"""
from __future__ import annotations

import re

# Matches "3+ years experience", "minimum of 2 years", "3-5 years of
# commercial experience", "experience: 4+ years". The experience keyword must
# appear within a short window of the number so that prose like "we've been
# making games for 20 years" is not mistaken for a requirement.
_YEARS_BEFORE = re.compile(
    r"(\d{1,2})\s*(?:\+|plus)?\s*(?:\s*(?:-|–|to)\s*\d{1,2}\s*\+?)?\s*"
    r"years?\b[^.\n]{0,45}?"
    r"(experience|exp\b|working|industry|professional|commercial|track record)",
    re.I,
)
_YEARS_AFTER = re.compile(
    r"(?:experience|exp\b)[^.\n]{0,35}?(\d{1,2})\s*(?:\+|plus)?\s*years?\b",
    re.I,
)


def stated_years(text: str) -> list[int]:
    """Every years-of-experience requirement we can find in the posting."""
    if not text:
        return []
    found = [int(m.group(1)) for m in _YEARS_BEFORE.finditer(text)]
    found += [int(m.group(1)) for m in _YEARS_AFTER.finditer(text)]
    # 0 is meaningless as a bar and >25 is almost certainly company history.
    return [y for y in found if 0 < y <= 25]


def _contains_any(haystack: str, needles) -> str | None:
    for n in needles:
        if n in haystack:
            return n
    return None


def is_uk(location: str, cfg: dict) -> bool:
    """UK filter that doesn't fall for London, Ontario or Cambridge, MA."""
    loc = f" {(location or '').lower()} "
    if not loc.strip():
        return False
    lcfg = cfg["location"]
    # Exclusions win. A non-UK country or US state marker disqualifies outright.
    if _contains_any(loc, lcfg["exclude_markers"]):
        return False
    if _contains_any(loc, lcfg["uk_markers"]):
        return True
    return _contains_any(loc, lcfg["uk_cities"]) is not None


def is_relevant(title: str, cfg: dict) -> bool:
    """Keeps a studio's finance and HR openings out of a technical feed."""
    t = (title or "").lower()
    return _contains_any(t, cfg["disciplines"]) is not None


def entry_level(title: str, description: str, cfg: dict) -> tuple[bool, str]:
    """Return (is_entry_level, human-readable reason).

    The reason is stored and shown on the page, so a reader can see WHY a role
    was included and tell us when we get it wrong.
    """
    ecfg = cfg["entry_level"]
    t = f" {(title or '').lower()} "

    hit = _contains_any(t, ecfg["negative_title"])
    if hit:
        return False, f"title says '{hit.strip()}'"

    hit = _contains_any(t, ecfg["positive_title"])
    if hit:
        return True, f"title says '{hit.strip()}'"

    # SmartRecruiters gives us a structured level; trust it when present.
    d = (description or "").lower()
    if "experience level: entry level" in d or "experience level: student" in d:
        return True, "employer tagged it entry level"
    if any(f"experience level: {lvl}" in d for lvl in
           ("mid-senior level", "senior level", "director", "executive")):
        return False, "employer tagged it senior"

    years = stated_years(description)
    if years:
        # The highest stated requirement is the gating one: a role asking for
        # "5+ years C++, 2+ years Unreal" is a five-year role.
        bar = max(years)
        if bar >= ecfg["max_years_experience"]:
            return False, f"asks for {bar}+ years"
        return True, f"asks for only {bar} year(s)"

    # No seniority signal and no stated requirement. Let it through and label
    # it honestly rather than silently guessing.
    return True, "no experience requirement stated"


def classify(job, cfg: dict) -> dict | None:
    """Apply every filter. Returns an enriched dict, or None if filtered out."""
    if not job.title or not job.url:
        return None
    if not is_uk(job.location, cfg):
        return None
    if not is_relevant(job.title, cfg):
        return None
    ok, reason = entry_level(job.title, job.description, cfg)
    if not ok:
        return None

    record = job.to_dict()
    record.pop("description", None)     # never republish employer copy
    record["level_reason"] = reason
    return record
