"""
Journal RSS Tracker
每周抓取期刊RSS，与上次记录对比，将新文章汇总发送邮件。
"""

import os
import json
import smtplib
import feedparser
import urllib.request
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

# ── RSS期刊列表 ──────────────────────────────────────────────────────────────
JOURNALS = [
    # 综合经济学
    ("The Quarterly Journal of Economics",            "https://academic.oup.com/rss/site_5504/3365.xml"),
    ("Journal of Political Economy",                  "https://www.journals.uchicago.edu/action/showFeed?type=etoc&feed=rss&jc=jpe"),
    ("The Review of Economic Studies",                "https://academic.oup.com/rss/site_5508/3369.xml"),
    ("Econometrica",                                  "https://onlinelibrary.wiley.com/feed/14680262/most-recent"),
    # 劳动/发展/公共
    ("Journal of Labor Economics",                    "https://www.journals.uchicago.edu/action/showFeed?type=etoc&feed=rss&jc=jole"),
    ("Labour Economics",                              "https://rss.sciencedirect.com/publication/science/09275371"),
    ("Journal of Development Economics",              "https://rss.sciencedirect.com/publication/science/03043878"),
    ("Journal of Public Economics",                   "https://rss.sciencedirect.com/publication/science/00472727"),
    ("The Economic Journal",                          "https://onlinelibrary.wiley.com/feed/14680297/most-recent"),
    ("Journal of Population Economics",               "https://link.springer.com/search.rss?facet-content-type=Article&facet-journal-id=148&channel-name=Journal+of+Population+Economics"),
    # 中国经济
    ("China Economic Review",                         "https://rss.sciencedirect.com/publication/science/1043951X"),
    # 金融
    ("Journal of Financial Economics",                "https://rss.sciencedirect.com/publication/science/0304405X"),
    ("The Journal of Finance",                        "https://onlinelibrary.wiley.com/feed/15406261/most-recent"),
    ("Review of Financial Studies",                   "https://academic.oup.com/rss/site_5510/3371.xml"),
    # 政治学/多学科/经济史
    ("American Journal of Political Science",         "https://onlinelibrary.wiley.com/action/showFeed?jc=15405907&type=etoc&feed=rss"),
    ("Proceedings of the National Academy of Sciences","https://www.pnas.org/action/showFeed?type=etoc&feed=rss&jc=PNAS"),
    ("The Journal of Economic History",               "https://www.cambridge.org/core/rss/product/id/677F550CB2C69EFA1656654D487DE504"),
]

# ── CrossRef期刊列表（无RSS的期刊，通过CrossRef API获取）────────────────────
CROSSREF_JOURNALS = [
    ("American Economic Review",               "0002-8282"),
    ("The Review of Economics and Statistics", "0034-6535"),
]

# ── 配置（从环境变量/GitHub Secrets读取）────────────────────────────────────
SEEN_FILE  = Path("seen_articles.json")
SMTP_HOST  = "smtp.163.com"
SMTP_PORT  = 465
SENDER     = os.environ["EMAIL_SENDER"]
PASSWORD   = os.environ["EMAIL_PASSWORD"]
RECIPIENTS = [r.strip() for r in os.environ["EMAIL_RECIPIENT"].split(",")]


def load_seen() -> set:
    if SEEN_FILE.exists():
        return set(json.loads(SEEN_FILE.read_text()))
    return set()


def save_seen(seen: set):
    SEEN_FILE.write_text(json.dumps(sorted(seen), indent=2, ensure_ascii=False))


def fetch_new_articles(seen: set) -> dict:
    import re
    import time
    results = {}
    for name, url in JOURNALS:
        try:
            feed = feedparser.parse(url)
            new_items = []
            for entry in feed.entries:
                uid = entry.get("id") or entry.get("link", "")
                if uid and uid not in seen:
                    published = entry.get("published_parsed") or entry.get("updated_parsed")
                    pub_str = ""
                    if published:
                        pub_str = datetime(*published[:3]).strftime("%Y-%m-%d")
                    authors = ""
                    if hasattr(entry, "authors"):
                        authors = ", ".join(a.get("name", "") for a in entry.authors)
                    elif hasattr(entry, "author"):
                        authors = entry.author
                    summary = entry.get("summary", "")
                    summary = re.sub(r"<[^>]+>", "", summary).strip()
                    if len(summary) > 300:
                        summary = summary[:300] + "…"
                    new_items.append({
                        "title":    entry.get("title", "(no title)").strip(),
                        "link":     entry.get("link", ""),
                        "authors":  authors,
                        "abstract": summary,
                        "date":     pub_str,
                        "uid":      uid,
                    })
            if new_items:
                results[name] = new_items
                print(f"  {name}: {len(new_items)} new")
            else:
                print(f"  {name}: no new articles")
        except Exception as e:
            print(f"  {name}: ERROR - {e}")
    return results


def fetch_crossref_articles(seen: set) -> dict:
    """通过CrossRef API获取无RSS期刊的最新文章（最近90天内发表的）"""
    results = {}
    cutoff_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    # 取90天前日期作为下限
    from datetime import timedelta
    from_date = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%d")
    for name, issn in CROSSREF_JOURNALS:
        try:
            url = (f"https://api.crossref.org/journals/{issn}/works"
                   f"?sort=published&order=desc&rows=50"
                   f"&filter=from-pub-date:{from_date}"
                   f"&select=DOI,title,author,published,abstract,URL")
            req = urllib.request.Request(url, headers={"User-Agent": "journal-tracker/1.0 (mailto:research@example.com)"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
            items = data.get("message", {}).get("items", [])
            new_items = []
            for item in items:
                uid = item.get("DOI", "")
                if not uid or uid in seen:
                    continue
                title = " ".join(item.get("title", ["(no title)"]))
                link  = item.get("URL") or f"https://doi.org/{uid}"
                authors = ", ".join(
                    f"{a.get('given','')} {a.get('family','')}".strip()
                    for a in item.get("author", [])[:5]
                )
                abstract = item.get("abstract", "")
                if abstract:
                    import re
                    abstract = re.sub(r"<[^>]+>", "", abstract).strip()
                    if len(abstract) > 300:
                        abstract = abstract[:300] + "…"
                pub_str = ""
                pd = item.get("published", {}).get("date-parts", [[]])[0]
                if pd:
                    pub_str = "-".join(str(p).zfill(2) for p in pd)
                new_items.append({
                    "title":    title,
                    "link":     link,
                    "authors":  authors,
                    "abstract": abstract,
                    "date":     pub_str,
                    "uid":      uid,
                })
            if new_items:
                results[name] = new_items
                print(f"  {name}: {len(new_items)} new (CrossRef)")
            else:
                print(f"  {name}: no new articles (CrossRef)")
        except Exception as e:
            print(f"  {name}: ERROR (CrossRef) - {e}")
    return results


def build_html(new_articles: dict, week_str: str) -> str:
    total = sum(len(v) for v in new_articles.values())
    sections = ""
    for journal, items in new_articles.items():
        rows = ""
        for a in items:
            rows += f"""
            <tr>
              <td style="padding:10px 0; border-bottom:1px solid #eee; vertical-align:top;">
                <div style="font-size:15px; font-weight:600; margin-bottom:4px;">
                  <a href="{a['link']}" style="color:#1a56db; text-decoration:none;">{a['title']}</a>
                </div>
                {"<div style='font-size:12px; color:#888; margin-bottom:2px;'>" + a['date'] + "</div>" if a['date'] else ""}
                {"<div style='font-size:12px; color:#666; margin-bottom:4px;'>" + a['authors'] + "</div>" if a['authors'] else ""}
                {"<div style='font-size:12px; color:#444; line-height:1.5;'>" + a['abstract'] + "</div>" if a['abstract'] else ""}
              </td>
            </tr>"""
        sections += f"""
        <div style="margin-bottom:28px;">
          <h2 style="font-size:16px; color:#1e293b; border-left:4px solid #1a56db;
                     padding-left:10px; margin:0 0 12px 0;">{journal}
            <span style="font-weight:normal; font-size:13px; color:#64748b;">({len(items)} articles)</span>
          </h2>
          <table width="100%" cellpadding="0" cellspacing="0">{rows}</table>
        </div>"""

    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"></head>
<body style="margin:0; padding:0; background:#f8fafc; font-family: -apple-system, Arial, sans-serif;">
  <div style="max-width:700px; margin:24px auto; background:#fff;
              border-radius:8px; overflow:hidden; box-shadow:0 1px 4px rgba(0,0,0,.08);">
    <div style="background:#1a56db; padding:24px 32px;">
      <h1 style="color:#fff; margin:0; font-size:20px;">📚 Journal Update Digest</h1>
      <p style="color:#bfdbfe; margin:6px 0 0; font-size:13px;">{week_str} · {total} new articles across {len(new_articles)} journals</p>
    </div>
    <div style="padding:24px 32px;">{sections}</div>
    <div style="padding:16px 32px; background:#f1f5f9; font-size:11px; color:#94a3b8;">
      Generated by journal-tracker · GitHub Actions
    </div>
  </div>
</body></html>"""


def send_email(html: str, week_str: str, total: int):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Journal Weekly Digest · {total} new articles — {week_str}"
    msg["From"]    = SENDER
    msg["To"]      = ", ".join(RECIPIENTS)
    msg.attach(MIMEText(html, "html", "utf-8"))
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
        server.login(SENDER, PASSWORD)
        server.sendmail(SENDER, RECIPIENTS, msg.as_string())
    print(f"Email sent to {', '.join(RECIPIENTS)}")


def main():
    week_str = datetime.now(timezone.utc).strftime("Week of %Y-%m-%d")
    print(f"=== Journal Tracker · {week_str} ===")
    seen = load_seen()
    print(f"Previously seen: {len(seen)} articles")
    new_articles = fetch_new_articles(seen)
    new_articles.update(fetch_crossref_articles(seen))
    total = sum(len(v) for v in new_articles.values())
    print(f"New articles found: {total}")
    if total == 0:
        print("Nothing new this week, skipping email.")
        return
    for items in new_articles.values():
        for a in items:
            seen.add(a["uid"])
    save_seen(seen)
    html = build_html(new_articles, week_str)
    send_email(html, week_str, total)
    print("Done.")


if __name__ == "__main__":
    main()
