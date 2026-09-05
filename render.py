"""Output: a static page and an RSS feed.

Deliberately dependency-free and free of network calls -- given a list of
records this module is pure, which makes it trivial to test and impossible for
a rendering bug to cost you an API call.

We publish title, company, location, age and a link. We never republish the
employer's job description: it isn't ours, and readers are better served by
being sent to the source anyway.
"""
from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path

DOCS = Path("docs")


def _e(s) -> str:
    return html.escape(str(s or ""), quote=True)


def _age_class(days: int) -> str:
    if days <= 7:
        return "fresh"
    if days <= 45:
        return "normal"
    return "stale"


def _age_label(rec: dict) -> str:
    d = rec.get("days_open", 0)
    if rec.get("is_new"):
        return "new today"
    if d == 0:
        return "listed today"
    if d == 1:
        return "open 1 day"
    return f"open {d} days"


def _row(rec: dict) -> str:
    badges = []
    days = rec.get("days_open", 0)
    badges.append(f'<span class="badge {_age_class(days)}">{_e(_age_label(rec))}</span>')
    reposts = rec.get("repost_count", 0)
    if reposts:
        times = "once" if reposts == 1 else f"{reposts}x"
        badges.append(f'<span class="badge warn">reposted {_e(times)}</span>')
    if rec.get("company_type") == "games":
        badges.append('<span class="badge games">games</span>')
    else:
        badges.append('<span class="badge adjacent">adjacent</span>')

    return f"""      <li class="job" data-type="{_e(rec.get('company_type'))}">
        <a class="title" href="{_e(rec.get('url'))}" rel="noopener nofollow" target="_blank">{_e(rec.get('title'))}</a>
        <div class="meta"><span class="co">{_e(rec.get('company'))}</span> &middot; {_e(rec.get('location'))}</div>
        <div class="badges">{''.join(badges)}</div>
        <div class="why">{_e(rec.get('level_reason'))} &middot; via {_e(rec.get('source'))}</div>
      </li>"""


CSS = """
:root{--bg:#fbfaf8;--fg:#1b1a17;--muted:#6b6862;--line:#e5e1da;--card:#fff;
--fresh:#0f7b4f;--freshbg:#e4f4ec;--stale:#9a5b00;--stalebg:#fdf0dc;
--warn:#a02c2c;--warnbg:#fbe6e6;--games:#3b3597;--gamesbg:#e9e8fb;
--adj:#4a5568;--adjbg:#edf0f4;--link:#1b4dd8}
@media (prefers-color-scheme:dark){:root{--bg:#14130f;--fg:#f2efe9;--muted:#9d988e;
--line:#2c2a25;--card:#1c1a16;--fresh:#6fd8a4;--freshbg:#10312280;--stale:#e5b25f;
--stalebg:#3a2a0d80;--warn:#f08a8a;--warnbg:#3a1a1a80;--games:#a9a4f5;--gamesbg:#20204a80;
--adj:#a8b2c0;--adjbg:#23272e80;--link:#8fb0ff}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
.wrap{max-width:820px;margin:0 auto;padding:32px 20px 64px}
h1{font-size:1.6rem;margin:0 0 6px;letter-spacing:-.01em}
.tagline{color:var(--muted);margin:0 0 20px;max-width:60ch}
.bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;
border-top:1px solid var(--line);border-bottom:1px solid var(--line);
padding:12px 0;margin-bottom:20px;font-size:.85rem;color:var(--muted)}
.bar .grow{flex:1}
button.filter{font:inherit;font-size:.85rem;cursor:pointer;border:1px solid var(--line);
background:var(--card);color:var(--fg);border-radius:999px;padding:4px 12px}
button.filter[aria-pressed="true"]{background:var(--fg);color:var(--bg);border-color:var(--fg)}
ul{list-style:none;margin:0;padding:0}
.job{background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:14px 16px;margin-bottom:10px}
.title{font-weight:600;color:var(--link);text-decoration:none;font-size:1.02rem}
.title:hover{text-decoration:underline}
.meta{color:var(--muted);font-size:.9rem;margin-top:2px}
.co{color:var(--fg);font-weight:500}
.badges{margin-top:9px;display:flex;flex-wrap:wrap;gap:6px}
.badge{font-size:.74rem;padding:2px 8px;border-radius:999px;font-weight:600;letter-spacing:.01em}
.fresh{background:var(--freshbg);color:var(--fresh)}
.normal{background:var(--adjbg);color:var(--adj)}
.stale{background:var(--stalebg);color:var(--stale)}
.warn{background:var(--warnbg);color:var(--warn)}
.games{background:var(--gamesbg);color:var(--games)}
.adjacent{background:var(--adjbg);color:var(--adj)}
.why{color:var(--muted);font-size:.78rem;margin-top:7px}
footer{margin-top:40px;padding-top:20px;border-top:1px solid var(--line);
color:var(--muted);font-size:.85rem}
footer h2{font-size:.95rem;color:var(--fg);margin:22px 0 8px}
footer a{color:var(--link)}
.health{display:flex;flex-wrap:wrap;gap:5px;margin-top:8px}
.dot{font-size:.72rem;padding:2px 7px;border-radius:5px;background:var(--adjbg);color:var(--adj)}
.dot.bad{background:var(--warnbg);color:var(--warn)}
.empty{padding:28px;text-align:center;color:var(--muted);
border:1px dashed var(--line);border-radius:10px}
"""

JS = """
const btns=document.querySelectorAll('button.filter');
const jobs=document.querySelectorAll('li.job');
const count=document.getElementById('count');
btns.forEach(b=>b.addEventListener('click',()=>{
  btns.forEach(x=>x.setAttribute('aria-pressed',x===b));
  const f=b.dataset.filter;let n=0;
  jobs.forEach(j=>{const show=(f==='all'||j.dataset.type===f);
    j.hidden=!show;if(show)n++;});
  if(count)count.textContent=n+(n===1?' role':' roles');
}));
"""


def render_html(records: list[dict], health: list[dict], cfg: dict) -> str:
    site = cfg["site"]
    now = datetime.now(timezone.utc)
    ok = [h for h in health if h["ok"]]
    bad = [h for h in health if not h["ok"]]

    rows = "\n".join(_row(r) for r in records) if records else ""
    body = f"<ul id='list'>\n{rows}\n    </ul>" if records else (
        '<p class="empty">No roles matched today. That is a real signal about '
        'the market, not a bug &mdash; check back tomorrow.</p>')

    dots = "".join(
        f'<span class="dot{"" if h["ok"] else " bad"}" title="{_e(h.get("error") or "")}">'
        f'{_e(h.get("name") or h.get("slug"))}: {h["count"] if h["ok"] else "failed"}</span>'
        for h in health)

    games_n = sum(1 for r in records if r.get("company_type") == "games")

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_e(site['title'])}</title>
<meta name="description" content="{_e(site['tagline'])}">
<link rel="alternate" type="application/rss+xml" title="{_e(site['title'])}" href="feed.xml">
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
  <h1>{_e(site['title'])}</h1>
  <p class="tagline">{_e(site['tagline'])}</p>

  <div class="bar">
    <button class="filter" data-filter="all" aria-pressed="true">All</button>
    <button class="filter" data-filter="games" aria-pressed="false">Games only</button>
    <button class="filter" data-filter="adjacent" aria-pressed="false">Adjacent</button>
    <span class="grow"></span>
    <span id="count">{len(records)} {'role' if len(records)==1 else 'roles'}</span>
  </div>

  {body}

  <footer>
    <p>Updated {_e(now.strftime('%d %b %Y, %H:%M'))} UTC &middot;
       {len(records)} roles ({games_n} at games studios) &middot;
       <a href="feed.xml">RSS</a></p>

    <h2>How this works</h2>
    <p>Every four hours this reads the public job boards of {len(health)} companies
       directly from the applicant tracking systems they already use
       (Greenhouse, Lever, Ashby, SmartRecruiters, Workable). Nothing is scraped
       from rendered pages and no listing text is republished &mdash; every link
       goes straight to the employer's own posting.</p>
    <p>A role appears only if it is in the UK, is technical or creative, and
       looks genuinely entry level. That last check reads the posting and rejects
       anything asking for
       {_e(cfg['entry_level']['max_years_experience'])}+ years, rather than
       trusting the "entry level" box the employer ticked. Each row shows the
       reason it passed, so you can tell when it gets it wrong.</p>
    <p><strong>Open N days</strong> is measured from when this tool first saw the
       role, so it is a floor, not an exact age. <strong>Reposted</strong> means
       the listing disappeared for at least three days and came back.</p>

    <h2>Sources ({len(ok)} healthy{f', {len(bad)} failing' if bad else ''})</h2>
    <div class="health">{dots}</div>

    <p style="margin-top:22px">Free, no accounts, no ads, no tracking.
       Built with an open source scraper &mdash; corrections welcome.</p>
  </footer>
</div>
<script>{JS}</script>
</body>
</html>
"""


def render_rss(records: list[dict], cfg: dict) -> str:
    site = cfg["site"]
    base = site["base_url"].rstrip("/")
    now = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")

    def esc(s):
        return html.escape(str(s or ""), quote=True)

    items = []
    for r in records[:100]:
        desc = (f"{r.get('company')} &mdash; {r.get('location')} &mdash; "
                f"{_age_label(r)}")
        if r.get("repost_count"):
            desc += f" &mdash; reposted {r['repost_count']}x"
        items.append(f"""    <item>
      <title>{esc(r.get('title'))} - {esc(r.get('company'))}</title>
      <link>{esc(r.get('url'))}</link>
      <guid isPermaLink="false">{esc(r.get('uid'))}</guid>
      <description>{esc(desc)}</description>
    </item>""")

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>{esc(site['title'])}</title>
    <link>{esc(base)}/</link>
    <description>{esc(site['tagline'])}</description>
    <language>en-gb</language>
    <lastBuildDate>{now}</lastBuildDate>
{chr(10).join(items)}
  </channel>
</rss>
"""


def write_all(records: list[dict], health: list[dict], cfg: dict,
              docs: Path = DOCS) -> None:
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "index.html").write_text(render_html(records, health, cfg), encoding="utf-8")
    (docs / "feed.xml").write_text(render_rss(records, cfg), encoding="utf-8")
    # A machine-readable copy costs nothing and makes the data reusable.
    (docs / "jobs.json").write_text(
        json.dumps({"generated": datetime.now(timezone.utc).isoformat(),
                    "count": len(records), "jobs": records}, indent=1),
        encoding="utf-8")
