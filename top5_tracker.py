import json
import re
import time
import urllib.request
from datetime import datetime, timedelta, timezone

import feedparser

TOP5_RSS_JOURNALS = [
    ("Journal of Political Economy", "https://www.journals.uchicago.edu/action/showFeed?type=etoc&feed=rss&jc=jpe"),
    ("Econometrica", "https://onlinelibrary.wiley.com/feed/14680262/most-recent"),
]

TOP5_CROSSREF_JOURNALS = [
    ("American Economic Review", "0002-8282"),
    ("The Quarterly Journal of Economics", "0033-5533"),
    ("The Review of Economic Studies", "0034-6527"),
]

TOP5_ISSUE_JOURNALS = [
    ("American Economic Review", "0002-8282"),
    ("The Quarterly Journal of Economics", "0033-5533"),
    ("Journal of Political Economy", "0022-3808"),
    ("Econometrica", "0012-9682"),
    ("The Review of Economic Studies", "0034-6527"),
]

TOP5_JOURNAL_NAMES = {name for name, _ in TOP5_RSS_JOURNALS + TOP5_CROSSREF_JOURNALS}
USER_AGENT = "journal-tracker/1.0 (mailto:research@example.com)"

SKIP_TITLE_PATTERNS = re.compile(
    r"\b(front\s*matter|back\s*matter|backmatter|frontmatter|erratum|corrigendum"
    r"|turnaround\s*time|recent\s*refer|acknowledgment|election\s*of\s*fellow"
    r"|annual\s*report|report\s*of\s*the\s*secretary|report\s*of\s*the\s*treasurer)\b",
    re.IGNORECASE,
)


def _fetch_json(url: str, retries: int = 4, base_sleep: float = 1.5):
    last_error = None
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read())
        except Exception as e:
            last_error = e
            retryable = "429" in str(e) or "timed out" in str(e).lower()
            if retryable and attempt < retries - 1:
                time.sleep(base_sleep * (attempt + 1))
                continue
            raise last_error
    raise last_error


def fetch_top5_recent_articles(cutoff_days: int = 21):
    results, errors = {}, {}
    cutoff = datetime.now(timezone.utc) - timedelta(days=cutoff_days)

    for name, url in TOP5_RSS_JOURNALS:
        try:
            feed = feedparser.parse(url)
            new_items = []
            for entry in feed.entries:
                uid = entry.get("id") or entry.get("link", "")
                if not uid:
                    continue
                published = entry.get("published_parsed") or entry.get("updated_parsed")
                pub_str = datetime(*published[:3]).strftime("%Y-%m-%d") if published else ""
                if published and datetime(*published[:6]) < cutoff.replace(tzinfo=None):
                    continue
                authors = ""
                if hasattr(entry, "authors"):
                    authors = ", ".join(a.get("name", "") for a in entry.authors)
                elif hasattr(entry, "author"):
                    authors = entry.author
                summary = re.sub(r"<[^>]+>", "", entry.get("summary", "")).strip()
                new_items.append({
                    "title": entry.get("title", "(no title)").strip(),
                    "link": entry.get("link", "").replace("?af=R", ""),
                    "authors": authors,
                    "abstract": summary,
                    "date": pub_str,
                    "uid": uid,
                    "doi": entry.get("prism_doi", ""),
                })
            if new_items:
                results[name] = new_items
        except Exception as e:
            errors[name] = str(e)

    from_date = (datetime.now(timezone.utc) - timedelta(days=cutoff_days)).strftime("%Y-%m-%d")
    for name, issn in TOP5_CROSSREF_JOURNALS:
        try:
            url = (
                f"https://api.crossref.org/journals/{issn}/works"
                f"?sort=published&order=desc&rows=50"
                f"&filter=from-pub-date:{from_date}"
                f"&select=DOI,title,author,published,abstract,URL"
            )
            data = _fetch_json(url)
            new_items = []
            for item in data.get("message", {}).get("items", []):
                uid = item.get("DOI", "")
                if not uid:
                    continue
                title = " ".join(item.get("title", ["(no title)"]))
                link = item.get("URL") or f"https://doi.org/{uid}"
                authors = ", ".join(
                    f"{a.get('given','')} {a.get('family','')}".strip()
                    for a in item.get("author", [])[:5]
                )
                abstract = re.sub(r"<[^>]+>", "", item.get("abstract", "")).strip()
                pd = item.get("published", {}).get("date-parts", [[]])[0]
                pub_str = "-".join(str(p).zfill(2) for p in pd) if pd else ""
                new_items.append({
                    "title": title,
                    "link": link,
                    "authors": authors,
                    "abstract": abstract,
                    "date": pub_str,
                    "uid": uid,
                    "doi": uid,
                })
            if new_items:
                results[name] = new_items
        except Exception as e:
            errors[name] = str(e)

    return results, errors


def fetch_top5_latest_issues():
    issue_payload, errors = {}, {}
    for name, issn in TOP5_ISSUE_JOURNALS:
        try:
            url = (
                f"https://api.crossref.org/journals/{issn}/works"
                f"?sort=published&order=desc&rows=50"
                f"&select=DOI,title,author,abstract,published,volume,issue"
                f"&filter=type:journal-article"
            )
            items = _fetch_json(url).get("message", {}).get("items", [])
            latest_vol, latest_iss = None, None
            for item in items:
                vol = item.get("volume", "")
                iss = item.get("issue", "")
                if vol and iss:
                    if latest_vol is None:
                        latest_vol, latest_iss = vol, iss
                    else:
                        try:
                            if int(vol) > int(latest_vol) or (vol == latest_vol and int(iss) > int(latest_iss)):
                                latest_vol, latest_iss = vol, iss
                        except ValueError:
                            pass
            if not latest_vol:
                continue

            url2 = (
                f"https://api.crossref.org/journals/{issn}/works"
                f"?rows=100"
                f"&select=DOI,title,author,abstract,published,URL,volume,issue"
                f"&filter=type:journal-article"
                f"&sort=published&order=desc"
            )
            all_items = _fetch_json(url2).get("message", {}).get("items", [])
            issue_items = [
                item for item in all_items
                if str(item.get("volume", "")) == latest_vol and str(item.get("issue", "")) == latest_iss
            ]
            articles = []
            for item in issue_items:
                title = " ".join(item.get("title", ["(no title)"]))
                if SKIP_TITLE_PATTERNS.search(title):
                    continue
                doi = item.get("DOI", "")
                link = item.get("URL") or (f"https://doi.org/{doi}" if doi else "")
                authors = ", ".join(
                    f"{a.get('given','')} {a.get('family','')}".strip()
                    for a in item.get("author", [])[:5]
                )
                abstract = re.sub(r"<[^>]+>", "", item.get("abstract", "")).strip()
                pd = item.get("published", {}).get("date-parts", [[]])[0]
                pub_str = "-".join(str(p).zfill(2) for p in pd) if pd else ""
                articles.append({
                    "title": title,
                    "link": link,
                    "authors": authors,
                    "abstract": abstract,
                    "date": pub_str,
                    "doi": doi,
                })
            if articles:
                issue_payload[name] = {
                    "volume": latest_vol,
                    "issue": latest_iss,
                    "articles": articles,
                }
        except Exception as e:
            errors[name] = str(e)
    return issue_payload, errors


def select_new_articles(public_articles: dict, seen: set, allowed_names=None):
    selected = {}
    allowed = set(allowed_names) if allowed_names is not None else None
    for name, items in public_articles.items():
        if allowed is not None and name not in allowed:
            continue
        filtered = [dict(item) for item in items if item.get("uid") and item["uid"] not in seen]
        if filtered:
            selected[name] = filtered
    return selected


def select_issue_sections(public_issue_payload: dict, seen: set, state: dict, allowed_names=None):
    selected = {}
    new_issue_seen = set()
    updated_state = dict(state)
    allowed = set(allowed_names) if allowed_names is not None else None

    for name, info in public_issue_payload.items():
        if allowed is not None and name not in allowed:
            continue
        issue_key = f"{info['volume']}/{info['issue']}"
        prev_key = state.get(name, "")
        if issue_key == prev_key:
            continue

        marked_articles = []
        for article in info["articles"]:
            doi = article.get("doi", "")
            doi_lower = doi.lower()
            previously_sent = (
                doi in seen or doi_lower in seen or any(doi_lower in s.lower() for s in seen if doi_lower)
            )
            if not previously_sent and doi:
                new_issue_seen.add(doi)
            marked = dict(article)
            marked["previously_sent"] = previously_sent
            marked_articles.append(marked)

        if marked_articles:
            selected[name] = {
                "volume": info["volume"],
                "issue": info["issue"],
                "articles": marked_articles,
            }
            updated_state[name] = issue_key

    return selected, new_issue_seen, updated_state
