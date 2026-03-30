"""
Journal RSS Tracker
每周抓取期刊RSS，与上次记录对比，将新文章汇总发送邮件。
"""

import os
import json
import re
import smtplib
import feedparser
import urllib.request
from datetime import datetime, timezone, timedelta, date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

# ── RSS期刊列表 ──────────────────────────────────────────────────────────────
JOURNALS = [
    # 综合经济学
    ("The Quarterly Journal of Economics",             "https://academic.oup.com/rss/site_5504/3365.xml"),
    ("Journal of Political Economy",                   "https://www.journals.uchicago.edu/action/showFeed?type=etoc&feed=rss&jc=jpe"),
    ("The Review of Economic Studies",                 "https://academic.oup.com/rss/site_5508/3369.xml"),
    ("Econometrica",                                   "https://onlinelibrary.wiley.com/feed/14680262/most-recent"),
    # 劳动/发展/公共
    ("Journal of Labor Economics",                     "https://www.journals.uchicago.edu/action/showFeed?type=etoc&feed=rss&jc=jole"),
    ("Journal of Development Economics",               "https://rss.sciencedirect.com/publication/science/03043878"),
    ("Journal of Public Economics",                    "https://rss.sciencedirect.com/publication/science/00472727"),
    ("The Economic Journal",                           "https://onlinelibrary.wiley.com/feed/14680297/most-recent"),
    ("Journal of Population Economics",                "https://link.springer.com/search.rss?facet-content-type=Article&facet-journal-id=148&channel-name=Journal+of+Population+Economics"),
    # 中国经济
    ("China Economic Review",                          "https://rss.sciencedirect.com/publication/science/1043951X"),
    # 金融
    ("Journal of Financial Economics",                 "https://rss.sciencedirect.com/publication/science/0304405X"),
    ("The Journal of Finance",                         "https://onlinelibrary.wiley.com/feed/15406261/most-recent"),
    ("Review of Financial Studies",                    "https://academic.oup.com/rss/site_5510/3371.xml"),
    # 经济史
    ("The Journal of Economic History",                "https://www.cambridge.org/core/rss/product/id/677F550CB2C69EFA1656654D487DE504"),
]

# ── CrossRef期刊列表（无RSS的期刊，通过CrossRef API获取）────────────────────
CROSSREF_JOURNALS = [
    ("American Economic Review",               "0002-8282"),
    ("The Review of Economics and Statistics", "0034-6535"),
]

# ── 配置（从环境变量/GitHub Secrets读取）────────────────────────────────────
SEEN_FILE        = Path("seen_articles.json")
FAIL_COUNTS_FILE = Path("fail_counts_journal_tracker.json")
SMTP_HOST        = "smtp.163.com"
SMTP_PORT        = 465
SENDER           = os.environ["EMAIL_SENDER"]
PASSWORD         = os.environ["EMAIL_PASSWORD"]
RECIPIENTS       = [r.strip() for r in os.environ["EMAIL_RECIPIENT"].split(",")]
ALERT_RECIPIENT  = os.environ.get("EMAIL_ALERT", "")
FAIL_THRESHOLD   = 5
SCRIPT_NAME      = "journal_tracker"
START_DATE       = date(2026, 3, 30)   # 第1期发送日期，用于计算期号


# ── 缓存读写 ──────────────────────────────────────────────────────────────────
def load_seen() -> set:
    if SEEN_FILE.exists():
        return set(json.loads(SEEN_FILE.read_text()))
    return set()


def save_seen(seen: set):
    SEEN_FILE.write_text(json.dumps(sorted(seen), indent=2, ensure_ascii=False))


def load_fail_counts() -> dict:
    if FAIL_COUNTS_FILE.exists():
        return json.loads(FAIL_COUNTS_FILE.read_text())
    return {}


def save_fail_counts(counts: dict):
    FAIL_COUNTS_FILE.write_text(json.dumps(counts, indent=2, ensure_ascii=False))


# ── 抓取 RSS ──────────────────────────────────────────────────────────────────
def fetch_new_articles(seen: set) -> tuple:
    results, errors = {}, {}
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    for name, url in JOURNALS:
        try:
            feed = feedparser.parse(url)
            new_items = []
            for entry in feed.entries:
                uid = entry.get("id") or entry.get("link", "")
                if uid and uid not in seen:
                    published = entry.get("published_parsed") or entry.get("updated_parsed")
                    pub_str = datetime(*published[:3]).strftime("%Y-%m-%d") if published else ""
                    # 跳过 7 天前的文章
                    if published and datetime(*published[:6]) < cutoff.replace(tzinfo=None):
                        continue
                    authors = ""
                    if hasattr(entry, "authors"):
                        authors = ", ".join(a.get("name", "") for a in entry.authors)
                    elif hasattr(entry, "author"):
                        authors = entry.author
                    summary = re.sub(r"<[^>]+>", "", entry.get("summary", "")).strip()
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
            errors[name] = str(e)
            print(f"  {name}: ERROR - {e}")
    return results, errors


# ── 抓取 CrossRef ─────────────────────────────────────────────────────────────
def fetch_crossref_articles(seen: set) -> tuple:
    """通过CrossRef API获取无RSS期刊的最新文章（最近90天内发表的）"""
    results, errors = {}, {}
    from_date = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    for name, issn in CROSSREF_JOURNALS:
        try:
            url = (f"https://api.crossref.org/journals/{issn}/works"
                   f"?sort=published&order=desc&rows=50"
                   f"&filter=from-pub-date:{from_date}"
                   f"&select=DOI,title,author,published,abstract,URL")
            req = urllib.request.Request(url, headers={"User-Agent": "journal-tracker/1.0 (mailto:research@example.com)"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
            new_items = []
            for item in data.get("message", {}).get("items", []):
                uid = item.get("DOI", "")
                if not uid or uid in seen:
                    continue
                title = " ".join(item.get("title", ["(no title)"]))
                link  = item.get("URL") or f"https://doi.org/{uid}"
                authors = ", ".join(
                    f"{a.get('given','')} {a.get('family','')}".strip()
                    for a in item.get("author", [])[:5]
                )
                abstract = re.sub(r"<[^>]+>", "", item.get("abstract", "")).strip()
                pd = item.get("published", {}).get("date-parts", [[]])[0]
                pub_str = "-".join(str(p).zfill(2) for p in pd) if pd else ""
                new_items.append({
                    "title": title, "link": link, "authors": authors,
                    "abstract": abstract, "date": pub_str, "uid": uid,
                })
            if new_items:
                results[name] = new_items
                print(f"  {name}: {len(new_items)} new (CrossRef)")
            else:
                print(f"  {name}: no new articles (CrossRef)")
        except Exception as e:
            errors[name] = str(e)
            print(f"  {name}: ERROR (CrossRef) - {e}")
    return results, errors


# ── 构建 HTML ─────────────────────────────────────────────────────────────────
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


# ── 发送邮件 ──────────────────────────────────────────────────────────────────
def send_email(html: str, week_str: str, total: int, issue_num: int):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"第{issue_num}期 · Journal Weekly Digest · {total} new articles — {week_str}"
    msg["From"]    = SENDER
    msg["To"]      = ", ".join(RECIPIENTS)
    msg.attach(MIMEText(html, "html", "utf-8"))
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
        server.login(SENDER, PASSWORD)
        server.sendmail(SENDER, RECIPIENTS, msg.as_string())
    print(f"Email sent to {', '.join(RECIPIENTS)}")


# ── 发送告警邮件 ──────────────────────────────────────────────────────────────
def send_alert(triggered: dict):
    """triggered: {journal_name: (error_msg, fail_count)}"""
    if not ALERT_RECIPIENT:
        print("EMAIL_ALERT not configured, skipping alert.")
        return
    rows = ""
    for name, (err_msg, count) in triggered.items():
        rows += f"""
          <tr>
            <td style="padding:8px 12px; border-bottom:1px solid #fee2e2; font-weight:600;">{name}</td>
            <td style="padding:8px 12px; border-bottom:1px solid #fee2e2; text-align:center;">{count}</td>
            <td style="padding:8px 12px; border-bottom:1px solid #fee2e2; font-family:monospace;
                       font-size:12px; color:#b91c1c; word-break:break-all;">{err_msg}</td>
          </tr>"""
    n = len(triggered)
    html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"></head>
<body style="margin:0; padding:0; background:#f8fafc; font-family:-apple-system, Arial, sans-serif;">
  <div style="max-width:700px; margin:24px auto; background:#fff;
              border-radius:8px; overflow:hidden; box-shadow:0 1px 4px rgba(0,0,0,.08);">
    <div style="background:#dc2626; padding:24px 32px;">
      <h1 style="color:#fff; margin:0; font-size:20px;">Journal Tracker · RSS Alert</h1>
      <p style="color:#fecaca; margin:6px 0 0; font-size:13px;">
        脚本 <strong>{SCRIPT_NAME}</strong> 中有 {n} 个期刊已连续 {FAIL_THRESHOLD} 周抓取失败
      </p>
    </div>
    <div style="padding:24px 32px;">
      <table width="100%" cellpadding="0" cellspacing="0"
             style="border-collapse:collapse; border:1px solid #fee2e2; border-radius:6px; overflow:hidden;">
        <thead>
          <tr style="background:#fef2f2;">
            <th style="padding:8px 12px; text-align:left; font-size:13px; color:#991b1b; white-space:nowrap;">期刊</th>
            <th style="padding:8px 12px; text-align:center; font-size:13px; color:#991b1b; white-space:nowrap;">连续失败周数</th>
            <th style="padding:8px 12px; text-align:left; font-size:13px; color:#991b1b;">错误信息</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
      <p style="margin:20px 0 0; font-size:13px; color:#475569; line-height:1.6;">
        处理方式：前往 <strong>GitHub Actions</strong> 查看详细日志，确认 RSS 地址失效后
        在 <code>{SCRIPT_NAME}.py</code> 中更新对应 URL 并提交。
      </p>
    </div>
    <div style="padding:16px 32px; background:#f1f5f9; font-size:11px; color:#94a3b8;">
      Generated by journal-tracker · GitHub Actions
    </div>
  </div>
</body></html>"""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[Journal Tracker · {SCRIPT_NAME}] {n} journal{'s' if n > 1 else ''} failing for {FAIL_THRESHOLD}+ weeks"
    msg["From"]    = SENDER
    msg["To"]      = ALERT_RECIPIENT
    msg.attach(MIMEText(html, "html", "utf-8"))
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
        server.login(SENDER, PASSWORD)
        server.sendmail(SENDER, [ALERT_RECIPIENT], msg.as_string())
    print(f"Alert sent to {ALERT_RECIPIENT}: {list(triggered.keys())}")


# ── 主流程 ────────────────────────────────────────────────────────────────────
def main():
    week_str  = datetime.now(timezone.utc).strftime("Week of %Y-%m-%d")
    issue_num = (datetime.now(timezone.utc).date() - START_DATE).days // 7 + 1
    print(f"=== Journal Tracker · {week_str} · 第{issue_num}期 ===")
    seen        = load_seen()
    fail_counts = load_fail_counts()
    print(f"Previously seen: {len(seen)} articles")

    new_articles, rss_errors      = fetch_new_articles(seen)
    crossref_results, cr_errors   = fetch_crossref_articles(seen)
    new_articles.update(crossref_results)
    all_errors = {**rss_errors, **cr_errors}

    # 更新失败计数：成功归零，失败+1
    all_names = [n for n, _ in JOURNALS] + [n for n, _ in CROSSREF_JOURNALS]
    for name in all_names:
        fail_counts[name] = fail_counts.get(name, 0) + 1 if name in all_errors else 0
    save_fail_counts(fail_counts)

    # 恰好达到阈值时触发告警
    triggered = {
        name: (all_errors[name], fail_counts[name])
        for name in all_errors
        if fail_counts[name] == FAIL_THRESHOLD
    }
    if triggered:
        send_alert(triggered)

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
    send_email(html, week_str, total, issue_num)
    print("Done.")


if __name__ == "__main__":
    main()
