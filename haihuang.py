"""
haihuang — 子集期刊追踪器
抓取指定期刊的最新文章，汇总后发送邮件通知。

用法：
  正常运行（增量，更新缓存）:  python haihuang.py
  测试运行（全量，不写缓存）:  python haihuang.py --test
"""

import os
import json
import sys
import re
import smtplib
import feedparser
import urllib.request
from datetime import datetime, timezone, timedelta, date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

# ── 期刊列表（RSS）───────────────────────────────────────────────────────────
JOURNALS = [
    # 社会学
    ("American Journal of Sociology",        "https://www.journals.uchicago.edu/action/showFeed?type=etoc&feed=rss&jc=ajs"),
    ("American Sociological Review",         "https://journals.sagepub.com/action/showFeed?jc=asr&type=etoc&feed=rss"),
    ("Annual Review of Sociology",           "https://www.annualreviews.org/action/showFeed?type=etoc&feed=rss&jc=soc"),
    ("Sociological Methods & Research",      "https://journals.sagepub.com/action/showFeed?jc=smr&type=etoc&feed=rss"),
    # 综合/多学科
    ("Proceedings of the National Academy of Sciences", "https://www.pnas.org/action/showFeed?type=etoc&feed=rss&jc=PNAS"),
    # 政治学
    ("American Journal of Political Science","https://onlinelibrary.wiley.com/action/showFeed?jc=15405907&type=etoc&feed=rss"),
    ("American Political Science Review",    "https://www.cambridge.org/core/rss/product/id/833A7242AC7B607BA7F6168DA072DB3B"),
    # 经济学
    ("Labour Economics",                     "https://rss.sciencedirect.com/publication/science/09275371"),
    ("Journal of Econometrics",              "https://rss.sciencedirect.com/publication/science/03044076"),
    ("Journal of Labor Economics",           "https://www.journals.uchicago.edu/action/showFeed?type=etoc&feed=rss&jc=jole"),
    ("Journal of Population Economics",      "https://link.springer.com/search.rss?facet-content-type=Article&facet-journal-id=148&channel-name=Journal+of+Population+Economics"),
    ("Journal of Development Economics",     "https://rss.sciencedirect.com/publication/science/03043878"),
    ("Journal of Public Economics",          "https://rss.sciencedirect.com/publication/science/00472727"),
    ("Journal of Economic Behavior and Organization", "https://rss.sciencedirect.com/publication/science/01672681"),
    ("The Economic Journal",                 "https://onlinelibrary.wiley.com/feed/14680297/most-recent"),
    ("The Quarterly Journal of Economics",   "https://academic.oup.com/rss/site_5504/3365.xml"),
    ("Journal of Political Economy",         "https://www.journals.uchicago.edu/action/showFeed?type=etoc&feed=rss&jc=jpe"),
    ("The Review of Economic Studies",       "https://academic.oup.com/rss/site_5508/3369.xml"),
    ("Econometrica",                         "https://onlinelibrary.wiley.com/feed/14680262/most-recent"),
    # 金融
    ("The Journal of Finance",               "https://onlinelibrary.wiley.com/feed/15406261/most-recent"),
    ("Review of Financial Studies",          "https://academic.oup.com/rss/site_5510/3371.xml"),
    # 经济史
    ("The Journal of Economic History",      "https://www.cambridge.org/core/rss/product/id/677F550CB2C69EFA1656654D487DE504"),
]

# ── CrossRef 期刊（无 RSS）──────────────────────────────────────────────────
CROSSREF_JOURNALS = [
    ("American Economic Review",                   "0002-8282"),
    ("The Review of Economics and Statistics",     "0034-6535"),
    ("American Economic Journal: Applied Economics","1945-7782"),
    ("American Economic Review: Insights",         "2640-205X"),
]

# ── 配置（从环境变量读取）────────────────────────────────────────────────────
SEEN_FILE        = Path("seen_haihuang.json")
FAIL_COUNTS_FILE = Path("fail_counts_haihuang.json")
SMTP_HOST        = "smtp.163.com"
SMTP_PORT        = 465
SENDER           = os.environ["EMAIL_SENDER"]
PASSWORD         = os.environ["EMAIL_PASSWORD"]
RECIPIENT        = os.environ["EMAIL_RECIPIENT_HAIHUANG"]
ALERT_RECIPIENT  = os.environ.get("EMAIL_ALERT", "")
FAIL_THRESHOLD   = 5
SCRIPT_NAME      = "haihuang"
START_DATE       = date(2026, 3, 30)   # 第1期发送日期，用于计算期号

TEST_MODE = "--test" in sys.argv


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
def fetch_rss(seen: set) -> tuple:
    results, errors = {}, {}
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    for name, url in JOURNALS:
        try:
            feed = feedparser.parse(url)
            new_items = []
            for entry in feed.entries:
                uid = entry.get("id") or entry.get("link", "")
                if not uid or uid in seen:
                    continue
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
                print(f"  {name}: {len(new_items)} 篇")
            else:
                print(f"  {name}: 无新文章")
        except Exception as e:
            errors[name] = str(e)
            print(f"  {name}: ERROR - {e}")
    return results, errors


# ── 抓取 CrossRef ─────────────────────────────────────────────────────────────
def fetch_crossref(seen: set) -> tuple:
    results, errors = {}, {}
    from_date = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    for name, issn in CROSSREF_JOURNALS:
        try:
            url = (
                f"https://api.crossref.org/journals/{issn}/works"
                f"?sort=published&order=desc&rows=50"
                f"&filter=from-pub-date:{from_date}"
                f"&select=DOI,title,author,published,abstract,URL"
            )
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "journal-tracker/1.0 (mailto:research@example.com)"}
            )
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
                print(f"  {name}: {len(new_items)} 篇 (CrossRef)")
            else:
                print(f"  {name}: 无新文章 (CrossRef)")
        except Exception as e:
            errors[name] = str(e)
            print(f"  {name}: ERROR (CrossRef) - {e}")
    return results, errors


# ── 构建 HTML ─────────────────────────────────────────────────────────────────
def build_html(articles: dict, week_str: str) -> str:
    total = sum(len(v) for v in articles.values())
    sections = ""
    for journal, items in articles.items():
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
      <p style="color:#bfdbfe; margin:6px 0 0; font-size:13px;">{week_str} · {total} new articles across {len(articles)} journals</p>
    </div>
    <div style="padding:24px 32px;">{sections}</div>
    <div style="padding:16px 32px; background:#f1f5f9; font-size:11px; color:#94a3b8;">
      Generated by journal-tracker · GitHub Actions
    </div>
  </div>
</body></html>"""


# ── 发送邮件 ──────────────────────────────────────────────────────────────────
def send_email(html: str, subject: str):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = SENDER
    msg["To"]      = RECIPIENT
    msg.attach(MIMEText(html, "html", "utf-8"))
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
        server.login(SENDER, PASSWORD)
        server.sendmail(SENDER, [RECIPIENT], msg.as_string())
    print(f"邮件已发送至 {RECIPIENT}")


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
    print(f"告警邮件已发送至 {ALERT_RECIPIENT}: {list(triggered.keys())}")


# ── 主流程 ────────────────────────────────────────────────────────────────────
def main():
    week_str  = datetime.now(timezone.utc).strftime("Week of %Y-%m-%d")
    issue_num = (datetime.now(timezone.utc).date() - START_DATE).days // 7 + 1
    mode_label = "【测试模式·全量】" if TEST_MODE else "【增量模式】"
    print(f"=== haihuang tracker · {week_str} · 第{issue_num}期 · {mode_label} ===")

    seen        = set() if TEST_MODE else load_seen()
    fail_counts = load_fail_counts()
    print(f"已记录文章数: {len(seen)}")

    articles, rss_errors    = fetch_rss(seen)
    cr_results, cr_errors   = fetch_crossref(seen)
    articles.update(cr_results)
    all_errors = {**rss_errors, **cr_errors}

    # 测试模式不更新失败计数，不发告警
    if not TEST_MODE:
        all_names = [n for n, _ in JOURNALS] + [n for n, _ in CROSSREF_JOURNALS]
        for name in all_names:
            fail_counts[name] = fail_counts.get(name, 0) + 1 if name in all_errors else 0
        save_fail_counts(fail_counts)

        triggered = {
            name: (all_errors[name], fail_counts[name])
            for name in all_errors
            if fail_counts[name] == FAIL_THRESHOLD
        }
        if triggered:
            send_alert(triggered)

    total = sum(len(v) for v in articles.values())
    print(f"本次获取文章: {total} 篇（共 {len(articles)} 个期刊有更新）")

    if total == 0:
        print("无新内容，跳过发送。")
        return

    html = build_html(articles, week_str)

    if TEST_MODE:
        subject = f"测试 · 第{issue_num}期 · Journal Weekly Digest · {total} articles — {week_str}"
        send_email(html, subject)
        print("测试完成，缓存未更新（下次正式运行仍可获取全量内容）。")
    else:
        subject = f"第{issue_num}期 · Journal Weekly Digest · {total} new articles — {week_str}"
        for items in articles.values():
            for a in items:
                seen.add(a["uid"])
        save_seen(seen)
        send_email(html, subject)
        print("完成，缓存已更新。")


if __name__ == "__main__":
    main()
