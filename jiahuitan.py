"""
jiahuitan — 子集期刊追踪器
抓取指定期刊的最新文章，汇总后发送邮件通知。

用法：
  正常运行（增量，更新缓存）:  python jiahuitan.py
  测试运行（全量，不写缓存）:  python jiahuitan.py --test
"""

import os
import json
import sys
import html
import re
import time
import smtplib
import feedparser
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta, date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

# ── 期刊列表（RSS）───────────────────────────────────────────────────────────
JOURNALS = [
    # OUP 期刊（QJE、RES）改用 CrossRef，见下方
    ("Journal of Political Economy",           "https://www.journals.uchicago.edu/action/showFeed?type=etoc&feed=rss&jc=jpe"),
    ("Econometrica",                           "https://onlinelibrary.wiley.com/feed/14680262/most-recent"),
    ("Journal of Labor Economics",             "https://www.journals.uchicago.edu/action/showFeed?type=etoc&feed=rss&jc=jole"),
    ("Journal of Development Economics",       "https://rss.sciencedirect.com/publication/science/03043878"),
    ("Journal of Public Economics",            "https://rss.sciencedirect.com/publication/science/00472727"),
    ("The Economic Journal",                   "https://onlinelibrary.wiley.com/feed/14680297/most-recent"),
    ("Journal of Population Economics",        "https://link.springer.com/search.rss?facet-content-type=Article&facet-journal-id=148&channel-name=Journal+of+Population+Economics"),
    ("China Economic Review",                  "https://rss.sciencedirect.com/publication/science/1043951X"),
    # 卫生经济学
    ("Journal of Health Economics",            "https://rss.sciencedirect.com/publication/science/01676296"),
    ("Health Economics",                       "https://onlinelibrary.wiley.com/feed/10991050/most-recent"),
    ("Social Science & Medicine",              "https://rss.sciencedirect.com/publication/science/02779536"),
]

# ── CrossRef 期刊（无 RSS）──────────────────────────────────────────────────
CROSSREF_JOURNALS = [
    ("American Economic Review",               "0002-8282"),
    ("The Review of Economics and Statistics", "0034-6535"),
    # OUP RSS 为静态当期期号 feed，改用 CrossRef
    ("The Quarterly Journal of Economics",     "0033-5533"),
    ("The Review of Economic Studies",         "0034-6527"),
]

# ── 配置（从环境变量读取）────────────────────────────────────────────────────
STATE_DIR        = Path(__file__).resolve().parent / "state"
SEEN_FILE        = STATE_DIR / "seen_jiahuitan.json"
FAIL_COUNTS_FILE = STATE_DIR / "fail_counts_jiahuitan.json"
SMTP_HOST        = "smtp.163.com"
SMTP_PORT        = 465
SENDER           = os.environ["EMAIL_SENDER"]
PASSWORD         = os.environ["EMAIL_PASSWORD"]
RECIPIENT        = os.environ["EMAIL_RECIPIENT_JIAHUITAN"]
ALERT_RECIPIENT  = os.environ.get("EMAIL_ALERT", "")
FAIL_THRESHOLD   = 5
SCRIPT_NAME      = "jiahuitan"
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
    cutoff = datetime.now(timezone.utc) - timedelta(days=21)
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
                # ScienceDirect RSS 不含标准作者/日期字段，从 summary 元数据中提取
                if "sciencedirect.com" in entry.get("link", ""):
                    if not authors:
                        m = re.search(r'Author\(s\):\s*(.+?)$', summary, re.MULTILINE)
                        if m:
                            authors = m.group(1).strip()
                    if not pub_str:
                        m = re.search(r'Publication date:\s*(.+?)Source:', summary)
                        if m:
                            pub_str = m.group(1).strip()
                new_items.append({
                    "title":    entry.get("title", "(no title)").strip(),
                    "link":     entry.get("link", "").replace("?af=R", ""),
                    "authors":  authors,
                    "abstract": summary,
                    "date":     pub_str,
                    "uid":      uid,
                    "doi":      entry.get("prism_doi", ""),
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
    from_date = (datetime.now(timezone.utc) - timedelta(days=21)).strftime("%Y-%m-%d")
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


# ── OpenAlex 摘要补充 ─────────────────────────────────────────────────────────
def _is_real_abstract(text: str) -> bool:
    """判断文本是否为真实摘要，排除 RSS 元数据占位字符串。"""
    if not text:
        return False
    if text.startswith("Publication date:"):
        return False
    if len(text) < 100:
        return False
    if re.search(r'\b(EarlyView|Ahead of Print)\b', text):
        return False
    return True


def _extract_doi(url: str) -> str:
    """从 URL 中提取 DOI（格式：10.xxxx/...）。"""
    m = re.search(r'(10\.\d{4,}/[^\s&?#"<>]+)', url)
    if not m:
        return ""
    return m.group(1).rstrip('.,;)')


def _reconstruct_abstract(inverted_index: dict) -> str:
    """将 OpenAlex 倒排索引格式还原为摘要文本。"""
    if not inverted_index:
        return ""
    words: dict[int, str] = {}
    for word, positions in inverted_index.items():
        for pos in positions:
            words[pos] = word
    return " ".join(words[i] for i in sorted(words))


def enrich_abstracts(articles: dict):
    """对摘要为空的文章通过 OpenAlex DOI 精确查询补充摘要。
    ScienceDirect 期刊（链接含 sciencedirect.com）无公开 DOI，跳过补充。
    """
    missing = [(j, i) for j, items in articles.items()
               for i, a in enumerate(items)
               if not _is_real_abstract(a["abstract"])
               and "sciencedirect.com" not in a.get("link", "")]
    if not missing:
        print("  摘要补充：无需补充")
        return

    print(f"  摘要补充：对 {len(missing)} 篇文章查询 OpenAlex...")
    headers = {"User-Agent": "journal-tracker/1.0 (mailto:research@example.com)"}
    enriched = 0

    for journal, idx in missing:
        articles[journal][idx]["abstract"] = ""   # 清除假摘要，避免元数据残留
        a = articles[journal][idx]
        abstract = ""

        # DOI 精确查询
        doi = a.get("doi") or _extract_doi(a["link"]) or _extract_doi(a["uid"])
        if doi:
            try:
                doi_url = urllib.parse.quote(f"https://doi.org/{doi}", safe="")
                url = f"https://api.openalex.org/works/{doi_url}?select=abstract_inverted_index"
                with urllib.request.urlopen(
                    urllib.request.Request(url, headers=headers), timeout=10
                ) as resp:
                    abstract = _reconstruct_abstract(
                        json.loads(resp.read()).get("abstract_inverted_index")
                    )
            except Exception:
                pass
            time.sleep(0.1)

        if abstract:
            articles[journal][idx]["abstract"] = abstract
            enriched += 1

    print(f"  摘要补充完成：{enriched}/{len(missing)} 篇补充成功")


# ── 构建 HTML ─────────────────────────────────────────────────────────────────
def _shorten(text: str, max_len: int = 420) -> str:
    if not text or len(text) <= max_len:
        return text or ""
    return text[:max_len].rstrip() + "..."


def _html_text(value: str, max_len=None) -> str:
    text = "" if value is None else str(value)
    if max_len is not None:
        text = _shorten(text, max_len)
    return html.escape(text, quote=False)


def _html_attr(value: str) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def build_html(articles: dict, week_str: str) -> str:
    total = sum(len(v) for v in articles.values())
    sections = ""
    for journal, items in articles.items():
        with_abs    = [a for a in items if _is_real_abstract(a.get("abstract", ""))]
        without_abs = [a for a in items if not _is_real_abstract(a.get("abstract", ""))]
        rows = ""

        for idx, a in enumerate(with_abs + without_abs, start=1):
            title = _html_text(a.get("title", "(no title)"))
            link = _html_attr(a.get("link", ""))
            date = _html_text(a.get("date", ""))
            authors = _html_text(a.get("authors", ""), max_len=420)
            abstract = _html_text(a.get("abstract", "")) if _is_real_abstract(a.get("abstract", "")) else ""
            rows += f"""
            <tr>
              <td style="padding:14px 0 18px 0; border-bottom:1px solid #e5e7eb; vertical-align:top;">
                <div style="font-size:17px; line-height:1.35; font-weight:700; color:#111827;">
                  <span style="display:inline-block; width:30px; color:#374151;">{idx}.</span>
                  <a href="{link}" style="color:#111827; text-decoration:none;">{title}</a>
                </div>
                {"<div style='font-size:15px; color:#374151; font-style:italic; line-height:1.45; margin:8px 0 0 30px;'>" + authors + "</div>" if authors else ""}
                <div style="font-size:14px; color:#6b7280; margin:7px 0 0 30px;">
                  {date + " | " if date else ""}<a href="{link}" style="color:#2563eb; text-decoration:underline;">Full article</a>
                </div>
                {"<div style='font-size:15px; color:#1f2937; line-height:1.65; margin:10px 0 0 30px;'>" + abstract + "</div>" if abstract else "<div style='font-size:14px; color:#6b7280; line-height:1.5; margin:10px 0 0 30px;'>Abstract not available from feed.</div>"}
              </td>
            </tr>"""

        journal_name = _html_text(journal)
        sections += f"""
        <div style="margin:42px 0 12px 0;">
          <h2 style="font-size:18px; color:#1f2937; letter-spacing:1px; text-transform:uppercase;
                     border-top:2px solid #111827; border-bottom:1px solid #d1d5db; padding:12px 0 10px 0;
                     margin:0 0 18px 0; font-weight:800;">{journal_name}
            <span style="font-weight:400; font-size:14px; color:#6b7280; letter-spacing:0; text-transform:none;">({len(items)} articles)</span>
          </h2>
          <table width="100%" cellpadding="0" cellspacing="0">{rows}</table>
        </div>"""

    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"></head>
<body style="margin:0; padding:0; background:#ffffff; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;">
  <div style="max-width:760px; margin:0 auto; padding:34px 42px 28px 42px; background:#ffffff;">
    <div style="border-bottom:1px solid #e5e7eb; padding-bottom:18px;">
      <h1 style="color:#111827; margin:0; font-size:25px; line-height:1.25; font-weight:700;">Journal Weekly Digest</h1>
      <p style="color:#6b7280; margin:8px 0 0; font-size:16px; line-height:1.45;">{week_str} · {total} new articles across {len(articles)} journals</p>
    </div>
    <p style="margin:26px 0 0 0; font-size:16px; color:#1f2937; line-height:1.55;">Abstracts are included when available. Titles link to the full article pages.</p>
    <div>{sections}</div>
    <div style="margin-top:32px; padding-top:14px; border-top:1px solid #e5e7eb; font-size:12px; color:#9ca3af;">
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
    print(f"=== jiahuitan tracker · {week_str} · 第{issue_num}期 · {mode_label} ===")

    seen        = set() if TEST_MODE else load_seen()
    fail_counts = load_fail_counts()
    print(f"已记录文章数: {len(seen)}")

    articles, rss_errors    = fetch_rss(seen)
    cr_results, cr_errors   = fetch_crossref(seen)
    articles.update(cr_results)
    enrich_abstracts(articles)
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
