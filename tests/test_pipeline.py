"""Tests for the whole pipeline, with the network stubbed out.

Run: python -m pytest tests/ -q
"""
import sys
from datetime import date, timedelta
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

try:                                # use the real thing when it's installed
    import pytest
except ImportError:                 # otherwise fall back to the mini runner
    from _mini import pytest

import sources                                    # noqa: E402
import store                                      # noqa: E402
import render                                     # noqa: E402
from classify import (CONFIRMED, POSSIBLE, classify, entry_level,
                      is_relevant, is_uk, stated_years)  # noqa: E402

CFG = yaml.safe_load((Path(__file__).parents[1] / "config.yml").read_text())


# ---------------------------------------------------------------- adapters --

PAYLOADS = {
    "boards-api.greenhouse.io": {"jobs": [
        {"id": 1, "title": "Graduate Gameplay Programmer",
         "location": {"name": "London, UK"},
         "absolute_url": "https://boards.greenhouse.io/x/jobs/1",
         "updated_at": "2026-08-20T10:00:00-04:00",
         "content": "&lt;p&gt;Join us. No prior industry experience required.&lt;/p&gt;"},
        {"id": 2, "title": "Senior Engine Programmer",
         "location": {"name": "Guildford, UK"},
         "absolute_url": "https://boards.greenhouse.io/x/jobs/2",
         "updated_at": "2026-07-01T10:00:00-04:00",
         "content": "&lt;p&gt;8+ years of professional experience.&lt;/p&gt;"},
    ]},
    "api.lever.co": [
        {"id": "abc", "text": "Junior Tools Engineer",
         "categories": {"location": "Manchester"},
         "hostedUrl": "https://jobs.lever.co/x/abc",
         "createdAt": 1787097600000,
         "descriptionPlain": "Work on our editor tooling.",
         "lists": [{"text": "Requirements",
                    "content": "<ul><li>1 year of commercial experience</li></ul>"}]},
        {"id": "def", "text": "Gameplay Engineer",
         "categories": {"location": "London, Ontario"},
         "hostedUrl": "https://jobs.lever.co/x/def",
         "createdAt": 1787097600000, "descriptionPlain": "Canada based."},
    ],
    "api.ashbyhq.com": {"jobs": [
        {"id": "u1", "title": "Software Engineer, Graphics", "location": "Bristol",
         "isListed": True, "publishedAt": "2026-09-01T09:00:00Z",
         "jobUrl": "https://jobs.ashbyhq.com/x/u1",
         "descriptionPlain": "You will have 5+ years of experience in C++."},
        {"id": "u2", "title": "Office Manager", "location": "Bristol",
         "isListed": True, "publishedAt": "2026-09-01T09:00:00Z",
         "jobUrl": "https://jobs.ashbyhq.com/x/u2", "descriptionPlain": ""},
    ]},
    "api.smartrecruiters.com": {"totalFound": 1, "content": [
        {"id": "sr1", "name": "QA Tester", "releasedDate": "2026-08-15T00:00:00.000Z",
         "location": {"city": "Newcastle", "region": "", "country": "uk"},
         "experienceLevel": {"label": "Entry level"}},
    ]},
    "apply.workable.com": {"jobs": [
        {"id": "w1", "shortcode": "AAA111", "title": "Placement - Data Analyst",
         "city": "Leeds", "country": "United Kingdom",
         "url": "https://apply.workable.com/x/j/AAA111/",
         "published_on": "2026-08-28",
         "description": "<p>A 12 month industrial placement.</p>",
         "requirements": "<p>No experience needed.</p>"},
    ]},
}


@pytest.fixture(autouse=True)
def stub_network(monkeypatch):
    def fake_get(url):
        for host, payload in PAYLOADS.items():
            if host in url:
                return payload
        raise sources.SourceError(f"unstubbed host: {url}")
    monkeypatch.setattr(sources, "_get", fake_get)


COMPANIES = {
    "greenhouse": [{"slug": "gh", "name": "GH Studio", "type": "games"}],
    "lever": [{"slug": "lv", "name": "LV Studio", "type": "games"}],
    "ashby": [{"slug": "as", "name": "AS Studio", "type": "games"}],
    "smartrecruiters": [{"slug": "sr", "name": "SR Studio", "type": "games"}],
    "workable": [{"slug": "wk", "name": "WK Ltd", "type": "adjacent"}],
}


def test_every_adapter_normalises():
    jobs, health = sources.fetch_all(COMPANIES)
    assert len(health) == 5
    assert all(h["ok"] for h in health), [h for h in health if not h["ok"]]
    assert len(jobs) == 8
    for j in jobs:
        assert j.uid.count(":") == 2
        assert j.title and j.url and j.company_type in {"games", "adjacent"}


def test_one_dead_board_does_not_kill_the_run(monkeypatch):
    original = sources._get

    def flaky(url):
        if "lever" in url:
            raise ConnectionError("boom")
        return original(url)

    monkeypatch.setattr(sources, "_get", flaky)
    jobs, health = sources.fetch_all(COMPANIES)
    failed = [h for h in health if not h["ok"]]
    assert len(failed) == 1 and failed[0]["ats"] == "lever"
    assert len(jobs) == 6          # the other four boards still returned


def test_html_is_stripped_and_unescaped():
    jobs, _ = sources.fetch_all({"greenhouse": COMPANIES["greenhouse"]})
    grad = next(j for j in jobs if "Graduate" in j.title)
    assert "<p>" not in grad.description
    assert "No prior industry experience" in grad.description


# -------------------------------------------------------------- classifier --

@pytest.mark.parametrize("loc,expected", [
    ("London, UK", True), ("Manchester", True), ("Guildford, England", True),
    ("Remote - United Kingdom", True), ("Dundee, Scotland", True),
    ("London, Ontario", False), ("Cambridge, MA", False),
    ("Newcastle, Australia", False), ("Berlin, Germany", False),
    ("Austin, TX", False), ("", False),
])
def test_uk_filter(loc, expected):
    assert is_uk(loc, CFG) is expected


@pytest.mark.parametrize("text,expected", [
    ("5+ years of experience in C++", [5]),
    ("minimum of 3 years commercial experience", [3]),
    ("3-5 years of professional experience", [3]),
    ("We have been making games for 20 years", []),
    ("experience: 4+ years", [4]),
    ("", []),
])
def test_years_extraction(text, expected):
    assert stated_years(text) == expected


@pytest.mark.parametrize("title,desc,tier", [
    ("Graduate Programmer", "8+ years experience", CONFIRMED),  # title wins
    ("Junior Engineer", "", CONFIRMED),
    ("Software Engineer", "1 year of experience", CONFIRMED),
    ("QA Tester", "Experience level: Entry level", CONFIRMED),
    ("Software Engineer", "", POSSIBLE),            # nothing either way
    ("Senior Gameplay Programmer", "", None),
    ("Lead Designer", "", None),
    ("Software Engineer", "5+ years of experience required", None),
    ("Producer II", "", None),
])
def test_entry_level(title, desc, tier):
    assert entry_level(title, desc, CFG)[0] == tier


@pytest.mark.parametrize("title", [
    "Staff Software Engineer",          # the bug that let 10 roles through
    "Staff Backend Engineer - Alerting",
    "Staff Product Designer (12-Month FTC)",
    "Head of Engineering",
    "Engineering Manager",
    "Principal Data Scientist",
])
def test_staff_and_senior_titles_are_rejected(title):
    """Substring matching missed 'Staff Software Engineer'; word matching doesn't."""
    assert entry_level(title, "", CFG)[0] is None


def test_seniority_described_in_prose_is_rejected():
    """54 of 59 real matches stated no years at all - prose is the real signal."""
    assert entry_level("Software Engineer",
                       "You have extensive experience with distributed systems.",
                       CFG)[0] is None
    assert entry_level("Software Engineer",
                       "You will lead a team of engineers.", CFG)[0] is None


@pytest.mark.parametrize("title,relevant", [
    ("Data Analyst", True),
    ("Software Engineer", True),
    ("Gameplay Programmer", True),
    ("Legal Counsel - Engine by Starling", False),   # matched 'engine' before
    ("Treasury IRRBB Analyst", False),
    ("Credit Analyst", False),
    ("Revenue Analyst", False),
    ("Digital Brand Designer", False),
    ("Talent Acquisition Partner", False),
])
def test_relevance_excludes_non_technical_roles(title, relevant):
    assert is_relevant(title, CFG) is relevant


def test_highest_requirement_gates():
    """'5+ years C++, 2+ years Unreal' is a five-year role, not a two-year one."""
    desc = "You have 5+ years of professional experience. Nice: 2 years with Unreal."
    assert entry_level("Engineer", desc, CFG)[0] is None


def test_full_classification_pass():
    jobs, _ = sources.fetch_all(COMPANIES)
    kept = [r for r in (classify(j, CFG) for j in jobs) if r]
    titles = sorted(r["title"] for r in kept)
    assert titles == ["Graduate Gameplay Programmer", "Junior Tools Engineer",
                      "Placement - Data Analyst", "QA Tester"]
    # Employer copy is never carried into the published record.
    assert all("description" not in r for r in kept)
    assert all(r["level_reason"] for r in kept)


# ------------------------------------------------------------------- store --

def _rec(uid, posted=None):
    return {"uid": uid, "title": "T", "company": "C", "company_type": "games",
            "location": "London", "url": "u", "source": "greenhouse",
            "posted_at": posted, "level_reason": "r"}


def test_first_run_marks_everything_new():
    state = {}
    out = store.update(state, [_rec("greenhouse:a:1")], {"greenhouse:a"})
    assert out[0]["is_new"] is True and out[0]["days_open"] == 0


def test_uses_employer_posted_date_when_available():
    state = {}
    posted = (date.today() - timedelta(days=30)).isoformat()
    out = store.update(state, [_rec("greenhouse:a:1", posted)], {"greenhouse:a"})
    assert out[0]["days_open"] == 30


def test_days_open_accumulates():
    old = (date.today() - timedelta(days=94)).isoformat()
    state = {"greenhouse:a:1": {"first_seen": old, "last_seen": old,
                                "repost_count": 0, "gone_since": None}}
    out = store.update(state, [_rec("greenhouse:a:1")], {"greenhouse:a"})
    assert out[0]["days_open"] == 94 and out[0]["is_new"] is False


def test_repost_counted_after_grace_period():
    gone = (date.today() - timedelta(days=10)).isoformat()
    state = {"greenhouse:a:1": {"first_seen": gone, "last_seen": gone,
                                "repost_count": 0, "gone_since": gone}}
    out = store.update(state, [_rec("greenhouse:a:1")], {"greenhouse:a"})
    assert out[0]["repost_count"] == 1


def test_brief_absence_is_not_a_repost():
    """A one-day blip must not manufacture a repost."""
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    state = {"greenhouse:a:1": {"first_seen": yesterday, "last_seen": yesterday,
                                "repost_count": 0, "gone_since": yesterday}}
    out = store.update(state, [_rec("greenhouse:a:1")], {"greenhouse:a"})
    assert out[0]["repost_count"] == 0


def test_failed_board_does_not_close_its_jobs():
    """If a board 404s, its jobs must not be marked as disappeared."""
    state = {"greenhouse:a:1": {"first_seen": "2026-01-01", "last_seen": "2026-01-01",
                                "repost_count": 0, "gone_since": None}}
    store.update(state, [], healthy_boards=set())          # board unreachable
    assert state["greenhouse:a:1"]["gone_since"] is None

    store.update(state, [], healthy_boards={"greenhouse:a"})  # board fine, job gone
    assert state["greenhouse:a:1"]["gone_since"] is not None


def test_prune_drops_long_closed_listings():
    old = (date.today() - timedelta(days=400)).isoformat()
    state = {"a:b:1": {"first_seen": old, "last_seen": old,
                       "repost_count": 0, "gone_since": old}}
    assert store.prune(state, 90) == {}


# ------------------------------------------------------------------ render --

def test_render_is_self_contained_and_escapes():
    recs = [{**_rec("greenhouse:a:1"), "title": 'Dev <script>alert(1)</script>',
             "days_open": 94, "repost_count": 2, "is_new": False, "first_seen": "x"}]
    health = [{"ats": "greenhouse", "slug": "a", "name": "A", "ok": True,
               "count": 1, "error": ""}]
    out = render.render_html(recs, health, CFG)
    assert "<script>alert(1)</script>" not in out
    assert "&lt;script&gt;" in out
    assert "open 94 days" in out and "reposted 2x" in out
    assert "http://" not in out.split("<footer>")[0].replace("https://", "")


def test_rss_is_wellformed():
    import xml.etree.ElementTree as ET
    recs = [{**_rec("greenhouse:a:1"), "days_open": 3, "repost_count": 0,
             "is_new": False}]
    xml = render.render_rss(recs, CFG)
    root = ET.fromstring(xml)
    assert root.find("./channel/item/title") is not None


def test_empty_day_renders_without_crashing():
    out = render.render_html([], [], CFG)
    assert "No roles matched today" in out


# --------------------------------------------------------- slug discovery --

def test_slug_variants_cover_common_spellings():
    from scan import slug_variants
    v = slug_variants("Splash Damage")
    assert "splashdamage" in v and "splash-damage" in v
    assert "splashdamagegames" in v or "splash-damage-games" in v

    v = slug_variants("Radical Forge")
    assert "radical-forge" in v and "radicalforge" in v


def test_slug_variants_strips_existing_suffix():
    from scan import slug_variants
    v = slug_variants("Supermassive Games")
    assert "supermassivegames" in v
    assert "supermassive" in v          # suffix dropped


def test_probe_flags_smartrecruiters_zero_as_ambiguous(monkeypatch, capsys=None):
    """0 jobs means 'not found' on SmartRecruiters but 'empty board' elsewhere."""
    import io, contextlib
    import scan
    monkeypatch.setattr(scan, "ADAPTERS", {
        "smartrecruiters": lambda s, n, t: [],
        "greenhouse": lambda s, n, t: [],
    })
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        dead = scan.probe({
            "smartrecruiters": [{"slug": "maybe", "name": "M", "type": "games"}],
            "greenhouse": [{"slug": "real", "name": "R", "type": "games"}],
        })
    out = buf.getvalue()
    assert dead == 0
    assert "unverifiable" in out          # smartrecruiters flagged
    assert "OK  greenhouse" in out        # greenhouse trusted


# ----------------------------------------------------------------- dedupe --

def _dup(uid, company, title, location, days, tier="possible"):
    return {"uid": uid, "company": company, "title": title, "location": location,
            "days_open": days, "repost_count": 0, "is_new": False, "tier": tier,
            "level_reason": "r", "company_type": "adjacent", "url": "u",
            "source": "workable"}


def test_dedupe_collapses_same_role_across_cities():
    """Starling posted 27 of 59 rows; most were one role in three cities."""
    from scan import dedupe
    out = dedupe([
        _dup("workable:s:1", "Starling", "IAM Analyst", "London", 5),
        _dup("workable:s:2", "Starling", "IAM Analyst", "Manchester", 12),
        _dup("workable:s:3", "Starling", "IAM Analyst", "Southampton", 9),
        _dup("workable:s:4", "Starling", "Android Engineer", "London", 3),
    ])
    assert len(out) == 2
    iam = next(r for r in out if r["title"] == "IAM Analyst")
    assert iam["location_count"] == 3
    assert "London" in iam["location"] and "Manchester" in iam["location"]
    # The role opened when the OLDEST of its postings appeared.
    assert iam["days_open"] == 12


def test_dedupe_keeps_the_stronger_tier():
    from scan import dedupe
    out = dedupe([
        _dup("workable:s:1", "X", "Engineer", "London", 4, tier="possible"),
        _dup("workable:s:2", "X", "Engineer", "Leeds", 4, tier="confirmed"),
    ])
    assert len(out) == 1 and out[0]["tier"] == "confirmed"


def test_dedupe_is_deterministic():
    from scan import dedupe
    rows = [_dup("workable:s:2", "X", "Engineer", "Leeds", 4),
            _dup("workable:s:1", "X", "Engineer", "London", 4)]
    assert dedupe(rows)[0]["uid"] == dedupe(list(reversed(rows)))[0]["uid"]
