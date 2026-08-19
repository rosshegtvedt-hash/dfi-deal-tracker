"""
scrapers/fmo.py — loads FMO (Nederlandse Financierings-Maatschappij voor
Ontwikkelingslanden) investments from FMO's own project disclosure.

Source: FMO's world map, https://www.fmo.nl/world-map — server-rendered,
no API key, no bot protection, paginated 20 per page. The loader crawls it
once per fund with a polite delay and merges the results.

Run:
    python -m scrapers.fmo

================= WHY THIS REPLACED THE EARLIER IATI SOURCE ================
This loader previously read FMO's IATI publication (NL-KVK-27078545). That
publication does NOT contain FMO's own-account investments at all: every one
of its activities belongs to a fund FMO manages on behalf of the Dutch
state, and it reports them at transaction grain, down to technical-assistance
line items of a few thousand dollars. The result was a tracker in which
"FMO" meant MASSIF, Building Prospects and AEF-I only, with a median deal of
about USD 0.3m and USD 1.9bn of volume across a decade — against an FMO
committed portfolio of roughly EUR 13bn.

FMO's world map publishes both: its own account (fund "FMO") and the
programme funds, each project tagged with the fund(s) financing it. This
loader keeps all of them and records the fund on every row, so own-account
lending can be separated from money FMO merely administers.
============================================================================

FUNDS — the `Funding` filter on the world map, and the codes it posts:
    FMO (2)                             — FMO's OWN ACCOUNT
    Access to Energy Fund (1)           — Dutch government programme funds
    Building Prospects (4)                and other managed vehicles
    DFCD (12)
    MASSIF (5)
    Mobilising Finance for Forests (14)
    Other funding (16)
    Ventures Program (13)

A project can be financed by more than one fund, so the loader crawls each
fund, merges on FMO's project id, and unions the fund names. Every project
appears ONCE, and `description` carries "Fund: FMO" or "Funds: FMO; MASSIF"
— the same treatment scrapers/afdb.py gives AfDB's sovereign/window flags.
To isolate FMO's own book, filter to rows whose description names the FMO
fund.

PAGINATION IS NOT STABLE. The same crawl returns some projects on two pages
and misses others: one pass over the unfiltered list yields 1,308 cards but
only ~1,288 distinct projects. The loader therefore crawls every fund view
AND the unfiltered list and unions them on project id, which recovers ~1,440
distinct investments — materially more than any single pass. Anything found
only in the unfiltered list has no fund attribution; it is loaded with
"Fund: not stated" and logged as 'fund_not_stated' rather than being guessed
into a fund.

Field mapping (world-map card -> our schema):
    ProjectList__projectTitle           -> project_name
    "Fund: ..." (derived, see above)    -> description
    "Country: ..."                      -> country
    "Sector: ..."                       -> sector (FMO's four sectors)
    "<CUR> <n> MLN" (title='Total FMO
      financing')                       -> amount_original + currency,
                                           converted via fx.py on the
                                           disclosure year
    "Date: M/D/YYYY"                    -> approval_date
    status span                         -> status
    project-detail link                 -> source_url

AMOUNTS are FMO's own financing for the project ("Total FMO financing"),
published in the deal's currency — mostly USD and EUR but also ZAR, INR and
others. Currencies fx_rates.csv has no rate for keep amount_original and get
amount_usd = NULL plus a logged 'fx_rate_missing', as elsewhere.

DATES are the disclosure date shown on the card, which is FMO's publication
date for the investment rather than a board-approval date.

E&S CATEGORY comes from each project-DETAIL page, which publishes an
"Environmental & Social Category (A, B+, B or C)" field the cards omit. That
is one request per project, so a full run is ~1,400 detail pages on top of
~90 list pages and takes roughly 25 MINUTES at the polite delay. A page with
no grade stores NULL; a page showing something outside A/B+/B/C stores NULL
and logs it, rather than inventing a category.

NOT PUBLISHED anywhere in this source, left NULL rather than inferred: instrument,
sponsor.
"""

import html as html_lib
import json
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

sys.path.insert(0, str(Path(__file__).parent.parent))
from database import get_connection, log_quality_issue, utc_now  # noqa: E402
from fx import to_usd  # noqa: E402

INSTITUTION = "FMO"
BASE_URL = "https://www.fmo.nl/world-map"
DETAIL_URL = "https://www.fmo.nl/project-detail/{}"
RAW_DIR = Path(__file__).parent.parent / "data" / "raw"
ES_CACHE = RAW_DIR / "fmo_es_category_cache.json"
UA_HEADER = {"User-Agent": "RCFH-Advisory DFI tracker (contact: rosshegtvedt@gmail.com)"}
DELAY_SECONDS = 0.7
PAGE_LIMIT = 200          # stop runaway pagination if the markup ever changes

OWN_ACCOUNT_FUND = "FMO"
FUNDS = {
    "2": OWN_ACCOUNT_FUND,
    "1": "Access to Energy Fund",
    "4": "Building Prospects",
    "12": "DFCD",
    "5": "MASSIF",
    "14": "Mobilising Finance for Forests",
    "16": "Other funding",
    "13": "Ventures Program",
}

# The whole disclosure is ~1,300 projects; anything far below that means the
# crawl or the markup broke, and loading it would replace good data with a
# fragment.
MIN_EXPECTED_PROJECTS = 800

# The detail page carries an E&S grade the world-map card does not. The label
# is rendered as "Environmental & Social Category (A, B+, B or C)" followed by
# the grade itself.
ES_LABEL_RE = re.compile(
    r"Environmental\s*&(?:amp;)?\s*Social\s*Category\s*\(A,\s*B\+,\s*B\s*or\s*C\)\s*"
    r"([^\s<]{1,12})", re.I)
# Grades FMO actually uses. Anything else is treated as "no grade published"
# and logged, rather than stored as if it were a category.
ES_VALUES = {"A", "B+", "B", "C"}
TAG_RE = re.compile(r"<[^>]+>")
SCRIPT_RE = re.compile(r"<script.*?</script>", re.S | re.I)

ITEM_RE = re.compile(
    r"<li class='ProjectList__item'[^>]*data-project-id='(?P<pid>\d+)'>.*?"
    r"href='(?P<url>[^']+)'.*?"
    r"<h3 class='ProjectList__projectTitle'>(?P<title>.*?)</h3>(?P<extras>.*?)</li>",
    re.S)
SPAN_RE = re.compile(r"<span[^>]*>(.*?)</span>", re.S)
AMOUNT_RE = re.compile(r"^([A-Z]{3})\s+([\d,]+(?:\.\d+)?)\s+MLN$")
TAGS_RE = re.compile(r"<[^>]+>")


def strip_tags(text):
    """Card text without markup. Entities are unescaped so country names
    arrive as "Côte d'Ivoire", not "Côte d&#039;Ivoire"."""
    return html_lib.unescape(TAGS_RE.sub("", text or "")).strip()


def parse_page(html):
    """Cards on one results page -> list of dicts."""
    out = []
    for m in ITEM_RE.finditer(html):
        spans = [s for s in (strip_tags(x) for x in SPAN_RE.findall(m.group("extras"))) if s]
        rec = {"id": m.group("pid"), "url": m.group("url"),
               "title": strip_tags(m.group("title")),
               "amount": None, "currency": None, "date": None,
               "country": None, "sector": None, "status": None}
        for span in spans:
            amount = AMOUNT_RE.match(span)
            if amount:
                rec["currency"] = amount.group(1)
                rec["amount"] = float(amount.group(2).replace(",", "")) * 1_000_000
            elif span.startswith("Date:"):
                rec["date"] = span.split(":", 1)[1].strip()
            elif span.startswith("Country:"):
                rec["country"] = span.split(":", 1)[1].strip() or None
            elif span.startswith("Sector:"):
                rec["sector"] = span.split(":", 1)[1].strip() or None
            else:
                rec["status"] = span
        out.append(rec)
    return out


def fetch_es_category(session, project_id):
    """E&S grade from one project-detail page.

    Returns (grade_or_None, note_or_None). A page that publishes no grade
    yields (None, None) — common and not an anomaly. A page showing something
    outside FMO's own A / B+ / B / C scale yields a note, because storing it
    silently would invent a category.
    """
    try:
        resp = session.get(DETAIL_URL.format(project_id), timeout=90)
    except requests.RequestException as exc:
        return None, f"detail page could not be fetched ({type(exc).__name__})"
    if resp.status_code != 200:
        return None, f"detail page returned HTTP {resp.status_code}"

    text = re.sub(r"\s+", " ", TAG_RE.sub(" ", SCRIPT_RE.sub(" ", resp.text)))
    match = ES_LABEL_RE.search(text)
    if not match:
        return None, None                      # page simply has no grade
    value = html_lib.unescape(match.group(1)).strip().rstrip(".,;")
    if value not in ES_VALUES:
        return None, (f"detail page shows {value!r} where an E&S grade was "
                      "expected; stored as NULL rather than as a category")
    return value, None


def add_es_categories(session, projects):
    """Visit every project's detail page for its E&S grade.

    This is the slow half of the loader — one request per project, ~1,400 on
    top of the ~90 list pages — so results are CACHED to disk as they arrive
    and a rerun only fetches what is still missing. A dropped connection or a
    closed laptop therefore costs a few pages, not the whole crawl. Delete
    ES_CACHE to force a full refresh.
    """
    cache = {}
    if ES_CACHE.exists():
        cache = json.loads(ES_CACHE.read_text(encoding="utf-8"))
    todo = [p for p in projects if p["id"] not in cache]
    print(f"E&S detail pages: {len(cache)} cached, {len(todo)} to fetch "
          f"(~{len(todo) * DELAY_SECONDS / 60:.0f} min at {DELAY_SECONDS}s each)")

    for n, proj in enumerate(todo, 1):
        grade, note = fetch_es_category(session, proj["id"])
        cache[proj["id"]] = {"es_category": grade, "es_note": note}
        if n % 100 == 0 or n == len(todo):
            ES_CACHE.write_text(json.dumps(cache), encoding="utf-8")
            got = sum(1 for v in cache.values() if v["es_category"])
            print(f"  {n}/{len(todo)} fetched, {got} of {len(cache)} have a grade")
        time.sleep(DELAY_SECONDS)
    ES_CACHE.write_text(json.dumps(cache), encoding="utf-8")

    for proj in projects:
        entry = cache.get(proj["id"], {})
        proj["es_category"] = entry.get("es_category")
        proj["es_note"] = entry.get("es_note")
    missing = sum(1 for p in projects if p["id"] not in cache)
    if missing:
        print(f"  WARNING: {missing} projects still unfetched — rerun to finish")
    return projects


def make_session():
    """fmo.nl drops the occasional connection during a long crawl, so retry
    with backoff rather than losing the run."""
    session = requests.Session()
    session.headers.update(UA_HEADER)
    retry = Retry(total=5, backoff_factor=1.5,
                  status_forcelist=[429, 500, 502, 503, 504],
                  allowed_methods=["GET"])
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def get_page(session, code, page, attempts=4):
    """One results page, retrying connection resets the adapter can't catch."""
    params = {"page": page}
    if code is not None:
        params["fund[]"] = code
    for attempt in range(attempts):
        try:
            return session.get(BASE_URL, timeout=120, params=params)
        except requests.exceptions.ConnectionError:
            if attempt == attempts - 1:
                raise
            time.sleep(3 * (attempt + 1))
    raise RuntimeError("unreachable")


def crawl_fund(session, code, name):
    """Every project in one view (a fund, or the whole list when code is None)."""
    found, page = [], 1
    while page <= PAGE_LIMIT:
        resp = get_page(session, code, page)
        # Paging past the last page 404s rather than returning an empty list.
        if resp.status_code == 404:
            break
        resp.raise_for_status()
        items = parse_page(resp.text)
        if not items:
            break
        found.extend(items)
        page += 1
        time.sleep(DELAY_SECONDS)
    print(f"  {name:<32} {len(found):>5} projects")
    return found


def fetch_all():
    """Crawl each fund plus the unfiltered list, merging on project id.

    The world map's paginated result set is NOT stable between requests —
    a single unfiltered crawl returns the same project on two pages ~16
    times and misses others. Crawling each (shorter) fund view as well and
    unioning by project id recovers materially more of the disclosure than
    any single pass: ~1,440 projects against the ~1,290 distinct ones a
    plain crawl of the full list yields.
    """
    session = make_session()
    projects = {}
    views = [(code, name) for code, name in FUNDS.items()] + [(None, "(all funds)")]
    for code, name in views:
        for rec in crawl_fund(session, code, name):
            existing = projects.setdefault(rec["id"], {**rec, "funds": []})
            if code is not None and name not in existing["funds"]:
                existing["funds"].append(name)
    return list(projects.values())


def archive(projects):
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    import json
    dest = RAW_DIR / f"fmo_worldmap_{date.today().isoformat()}.json"
    dest.write_text(json.dumps(projects, indent=1, ensure_ascii=False),
                    encoding="utf-8")
    print(f"Archived {len(projects)} projects to {dest.name}")


def parse_date(value):
    """'7/27/2026' -> ISO. Returns (iso_or_None, note_or_None)."""
    if not value:
        return None, "no date on the card"
    try:
        return datetime.strptime(value, "%m/%d/%Y").date().isoformat(), None
    except ValueError:
        return None, f"unparseable date {value!r}"


def load(projects) -> None:
    if len(projects) < MIN_EXPECTED_PROJECTS:
        raise SystemExit(
            f"Only {len(projects)} projects crawled — the world map's markup or "
            "pagination has probably changed. Refusing to load; check the parser.")

    own = sum(1 for p in projects if OWN_ACCOUNT_FUND in p["funds"])
    print(f"{len(projects)} projects ({own} on FMO's own account)")

    conn = get_connection()
    scraped_at = utc_now()
    inserted = issues = 0
    try:
        conn.execute("DELETE FROM projects WHERE institution = ?", (INSTITUTION,))
        conn.execute("DELETE FROM quality_issues WHERE institution = ?", (INSTITUTION,))

        for p in projects:
            name = p["title"] or None
            if name is None:
                log_quality_issue(conn, INSTITUTION, None, "missing_project_name",
                                  "card has no title", p)
                issues += 1

            funds = p["funds"]
            if funds:
                label = "Fund" if len(funds) == 1 else "Funds"
                description = f"{label}: {'; '.join(funds)}"
            else:
                # Present in the full list but under no fund filter.
                description = "Fund: not stated"
                log_quality_issue(
                    conn, INSTITUTION, name, "fund_not_stated",
                    "the world map lists this investment but it appears under no "
                    "fund filter, so it cannot be attributed to FMO's own account "
                    "or to a managed programme fund", p)
                issues += 1

            approval_date, date_note = parse_date(p["date"])
            if date_note:
                log_quality_issue(conn, INSTITUTION, name, "unparseable_date",
                                  date_note, p)
                issues += 1

            if p["country"] is None:
                log_quality_issue(conn, INSTITUTION, name, "missing_country",
                                  "card shows no country", p)
                issues += 1

            if p.get("es_note"):
                log_quality_issue(conn, INSTITUTION, name,
                                  "unresolved_es_category", p["es_note"], p)
                issues += 1

            amount, currency, amount_usd = p["amount"], p["currency"], None
            if amount is None:
                log_quality_issue(conn, INSTITUTION, name, "missing_amount",
                                  "card shows no financing amount", p)
                issues += 1
            else:
                year = int(approval_date[:4]) if approval_date else None
                amount_usd, fx_note = to_usd(amount, currency, year)
                if fx_note and amount_usd is None:
                    log_quality_issue(conn, INSTITUTION, name, "fx_rate_missing",
                                      fx_note, p)
                    issues += 1
                elif fx_note:
                    log_quality_issue(conn, INSTITUTION, name,
                                      "fx_rate_approximated", fx_note, p)
                    issues += 1

            conn.execute(
                """INSERT INTO projects
                   (institution, project_name, country, region, sector, subsector,
                    instrument, amount_original, currency, amount_usd,
                    approval_date, fiscal_year, status, es_category, sponsor,
                    description, source_url, scraped_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    INSTITUTION,
                    name,
                    p["country"],
                    None,   # region: canonical_region comes from country harmonization
                    p["sector"],
                    None,
                    None,   # instrument: not on the card
                    amount,
                    currency,
                    amount_usd,
                    approval_date,
                    None,
                    p["status"],
                    p.get("es_category"),
                    None,   # sponsor: not on the card
                    description,
                    p["url"],
                    scraped_at,
                ),
            )
            inserted += 1

        conn.commit()
    finally:
        conn.close()

    print(f"Inserted {inserted} FMO investments ({issues} quality issues logged).")


if __name__ == "__main__":
    print(f"Crawling {BASE_URL} by fund")
    all_projects = fetch_all()
    all_projects = add_es_categories(make_session(), all_projects)
    archive(all_projects)
    load(all_projects)
