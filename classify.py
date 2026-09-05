"""Filtering: is this role in the UK, is it relevant, and is it REALLY entry level?

The last question is the one that matters. Every big job board has an
"entry level" filter and every one of them returns roles demanding three years
of experience, because they trust whatever box the employer ticked.

The first version of this trusted stated years of experience. Auditing 59 real
matches showed why that fails: 54 of them stated no number at all. UK postings
describe seniority in prose -- "extensive experience", "you will lead" -- far
more often than they count it. So detection now works on three signals, and the
result is a confidence tier rather than a yes/no:

    confirmed  explicit junior/grad/intern signal, or <2 stated years
    possible   no seniority signal anywhere, but nothing proving it's junior
    rejected   any seniority signal in the title, the prose, or the years
"""
from __future__ import annotations

import re

CONFIRMED = "confirmed"
POSSIBLE = "possible"

# Matches "3+ years experience", "minimum of 2 years", "3-5 years of commercial
# experience", "experience: 4+ years". The experience keyword must appear within
# a short window of the number, so "making games for 20 years" isn't read as a
# requirement.
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
    return [y for y in found if 0 < y <= 25]


def _word_hit(haystack: str, needles) -> str | None:
    """Whole-word match.

    Substring matching was the bug that let ten "Staff Software Engineer" roles
    through: the list held "staff engineer", which doesn't occur in that string.
    Matching on word boundaries means a single "staff" entry catches them all,
    without "staff" also matching "staffing".
    """
    text = (haystack or "").lower()
    for n in needles:
        n = str(n).lower().strip()
        if not n:
            continue
        if re.search(rf"(?<![a-z0-9]){re.escape(n)}(?![a-z0-9])", text):
            return n
    return None


def _substr_hit(haystack: str, needles) -> str | None:
    """Plain substring match, for multi-word phrases where boundaries hurt."""
    text = (haystack or "").lower()
    for n in needles:
        if str(n).lower().strip() in text:
            return str(n)
    return None


def is_uk(location: str, cfg: dict) -> bool:
    """UK filter that doesn't fall for London, Ontario or Cambridge, MA."""
    loc = f" {(location or '').lower()} "
    if not loc.strip():
        return False
    lcfg = cfg["location"]
    if _substr_hit(loc, lcfg["exclude_markers"]):
        return False
    if _substr_hit(loc, lcfg["uk_markers"]):
        return True
    return _substr_hit(loc, lcfg["uk_cities"]) is not None


def is_relevant(title: str, cfg: dict) -> bool:
    """Technical or creative roles only.

    Two gates, because one wasn't enough. "Analyst" and "Designer" are real
    tech titles, but they are also finance, legal and marketing titles -- the
    exclusion list is what separates a Data Analyst from a Treasury Analyst.
    """
    if _substr_hit(title, cfg.get("exclude_titles", [])):
        return False
    return _substr_hit(title, cfg["disciplines"]) is not None


def entry_level(title: str, description: str, cfg: dict) -> tuple[str | None, str]:
    """Return (tier, human-readable reason).

    The reason is published on every row, so a reader can see why a role was
    included and tell us when it's wrong.
    """
    ecfg = cfg["entry_level"]

    hit = _word_hit(title, ecfg["negative_title"])
    if hit:
        return None, f"title says '{hit}'"

    hit = _substr_hit(title, ecfg["positive_title"])
    if hit:
        return CONFIRMED, f"title says '{hit}'"

    d = (description or "").lower()

    # SmartRecruiters gives a structured level; trust it when present.
    if "experience level: entry level" in d or "experience level: student" in d:
        return CONFIRMED, "employer tagged it entry level"
    if any(f"experience level: {lvl}" in d for lvl in
           ("mid-senior level", "senior level", "director", "executive")):
        return None, "employer tagged it senior"

    years = stated_years(description)
    if years:
        # The highest stated requirement gates the role: "5+ years C++, 2+ years
        # Unreal" is a five-year job.
        bar = max(years)
        if bar >= ecfg["max_years_experience"]:
            return None, f"asks for {bar}+ years"
        return CONFIRMED, f"asks for only {bar} year(s)"

    hit = _substr_hit(d, ecfg.get("seniority_phrases", []))
    if hit:
        return None, f"posting says '{hit}'"

    # Nothing proves it's junior, but nothing marks it senior either. Publish
    # it in a separate, clearly-labelled section rather than pretending.
    return POSSIBLE, "no seniority stated either way"


def classify(job, cfg: dict) -> dict | None:
    """Apply every filter. Returns an enriched dict, or None if filtered out."""
    if not job.title or not job.url:
        return None
    if not is_uk(job.location, cfg):
        return None
    if not is_relevant(job.title, cfg):
        return None
    tier, reason = entry_level(job.title, job.description, cfg)
    if tier is None:
        return None

    record = job.to_dict()
    record.pop("description", None)     # never republish employer copy
    record["tier"] = tier
    record["level_reason"] = reason
    return record
