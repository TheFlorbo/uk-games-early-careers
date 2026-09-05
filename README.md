# UK Games & Tech — Early Careers

A free, automatically updated list of genuinely entry-level UK roles for people
trying to get into the games industry — including the adjacent software and data
jobs that realistically get you there.

**Live page:** https://theflorbo.github.io/uk-games-early-careers
**RSS:** `/feed.xml` · **JSON:** `/jobs.json`

No accounts, no ads, no tracking, no paywall. Runs entirely on GitHub Actions.

---

## Why this exists

UK universities enrolled around 15,500 students on games and animation courses
in 2023/24, up from about 4,000 a decade earlier. Meanwhile studios fill roughly
78% of vacancies from people already in the industry, and one analysis of UK
games openings found only 34 of 1,170 were entry level.

So the hard part isn't choosing between opportunities — it's finding the few
that exist, and not wasting applications on roles that say "junior" and mean
five years. This tries to help with both.

## What makes it different from a normal job board

**It shows you how long a role has actually been open.** Aggregators happily
present a six-month-old listing as though it appeared this morning. Because this
records what it saw yesterday, it can tell you a role has been open 94 days — and
flag when a listing vanished and came back, which is usually a sign a search
isn't going well.

**Its "entry level" filter actually reads the posting.** Every big board trusts
whatever seniority box the employer ticked, which is why searching "entry level"
returns roles demanding three years. This reads the description, extracts stated
experience requirements, and rejects anything above the configured threshold
unless the title is explicitly a grad/intern/junior role. Every listing shows the
reason it passed, so you can see when the filter gets it wrong.

**It links to the employer, not to itself.** Titles, companies, locations and
links only — no republished job descriptions. You always land on the company's
own posting.

## How it works

```
companies.yml ──> sources.py ──> classify.py ──> store.py ──> render.py ──> docs/
   (who to        (5 ATS         (UK? relevant?   (how old?     (HTML +
    watch)         adapters)      entry level?)    reposted?)    RSS + JSON)
```

Data comes from the **public job board endpoints of the applicant tracking
systems studios already use** — Greenhouse, Lever, Ashby, SmartRecruiters and
Workable. These are the same feeds that power companies' own careers pages.

That choice matters:

- **No API keys.** Nothing secret lives in this repo, so it is safe to be public.
- **No HTML scraping.** Nothing breaks when a site changes a CSS class.
- **No licensing grey area** around republishing an aggregator's data.

The trade-off is coverage: only companies listed in `companies.yml` are checked.
That's a deliberate exchange of breadth for reliability and a clean legal
footing. Adding a company takes one line.

## Design decisions worth knowing about

**One dead board never kills a run.** Each company is fetched inside its own
error boundary, and the page footer shows the health of every source. Silent
source rot is the most common way a feed like this decays without anyone
noticing.

**A failed board does not mark its jobs as closed.** If a company's endpoint
404s, its roles simply vanish from the response — which naively looks identical
to every role being filled. Ageing is therefore applied only to boards that were
fetched successfully.

**A brief outage does not manufacture reposts.** A listing must be absent for at
least three days before its return counts as a repost, so one flaky night
doesn't put a "reposted" badge on half the page.

**Rendering is pure.** `render.py` makes no network calls and holds no state, so
a display bug can never cost an HTTP request and the output is trivially
testable.

**`days_open` is a floor, not a fact.** Where an ATS reports a real publication
date it is used; otherwise the clock starts the first time this tool saw the
role. The page says so.

## Running it

```bash
pip install -r requirements.txt

python scan.py --probe      # check which company slugs are live
python scan.py --find "Studio Name"   # hunt for a company's job board
python scan.py --offline    # run against test fixtures, no network
python scan.py --dry-run    # full run, writes nothing
python scan.py              # full run, writes docs/ and state/
python tests/run.py         # 41 tests, no pytest required
```

`tests/run.py` uses a small pytest shim so the suite runs with zero installs.
If you have pytest, `python -m pytest tests/ -q` works too.

## Setting it up yourself

1. Fork or copy this repo. **Start it fresh** — never convert a private repo
   that has ever contained API keys, since they remain readable in the history.
2. Edit `config.yml` — set `site.base_url` to your GitHub Pages URL.
3. Add companies with `python scan.py --find "Company Name"`, which tries every
   plausible slug against all five ATSs and prints a line to paste into
   `companies.yml`. Then run `python scan.py --probe` to confirm.
4. In repo settings, enable **Pages → deploy from branch → `main` → `/docs`**.
5. Enable Actions. It runs every four hours and commits the updated page.

## Known limitations

- **Coverage is only as good as `companies.yml`.** This is a curated feed, not a
  crawl of the whole market. Use it alongside the big boards, not instead.
- **The entry-level filter is heuristic.** It will occasionally pass a role that
  wants more experience than it admits, and occasionally reject a good one whose
  description mentions a number oddly. The reason is printed on every row so
  mistakes are visible rather than hidden.
- **Roles with no stated requirement are let through** and labelled as such,
  because rejecting them would lose too many genuine graduate postings.
- **Games coverage is the weak spot.** Most UK studios host their own careers
  pages rather than using a supported ATS, so the adjacent-tech side of the feed
  is currently much deeper than the games side. Expanding it is the main ongoing
  job, and `--find` is the tool for it.
- **SmartRecruiters cannot be probed reliably.** It returns an empty list rather
  than a 404 for an unknown company, so "0 jobs" there might mean an empty board
  or a wrong slug. `--probe` flags these instead of passing them silently; verify
  by opening `jobs.smartrecruiters.com/<slug>` yourself.

## Contributing

Corrections to the filters and additions to `companies.yml` are welcome. If you
spot a role that shouldn't be here, open an issue with the link — the reason it
passed is shown on the page and makes the fix obvious.

## Licence

MIT. Job listing data belongs to the respective employers; this publishes only
titles, locations and links back to their own postings.
