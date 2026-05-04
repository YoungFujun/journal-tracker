"""
tracker_core — 公共执行核心
所有预设脚本共享的抓取、摘要补充、HTML渲染、发信、状态持久化逻辑。
预设脚本只需定义 TrackerConfig 并调用 run_tracker()。
"""

import os
import sys
import json
import html
import re
import time
import smtplib
import calendar
import feedparser
import urllib.request
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta, date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Callable

import top5_tracker

STATE_DIR   = Path(__file__).resolve().parent / "state"
SMTP_HOST   = "smtp.163.com"
SMTP_PORT   = 465
FAIL_THRESHOLD = 5


# ── 配置 dataclass ─────────────────────────────────────────────────────────────

@dataclass
class TrackerConfig:
    script_name: str                            # 对应状态文件后缀，如 "xu"
    start_date: date                            # 第1期发送日期，用于计算期号
    env_recipient: str                          # 收件人环境变量名，如 "EMAIL_RECIPIENT_XU"
    journals: list                              # RSS期刊列表：[(name, url), ...]
    crossref_journals: list                     # CrossRef期刊列表：[(name, issn), ...]
    # 扩展点：返回False表示该摘要文本不是真实摘要（在标准规则之后再检查）
    extra_abstract_filter: Callable[[str], bool] | None = None
    # 扩展点：对RSS每个条目做预设特有处理；返回None跳过该条目，返回修改后的item dict
    per_entry_transform: Callable[[object, dict], dict | None] | None = None


# ── 状态文件路径（根据 script_name 自动生成，与现有文件名完全一致）────────────

def _seen_file(cfg: TrackerConfig) -> Path:
    name = "seen_articles.json" if cfg.script_name == "journal_tracker" else f"seen_{cfg.script_name}.json"
    return STATE_DIR / name

def _fail_counts_file(cfg: TrackerConfig) -> Path:
    return STATE_DIR / f"fail_counts_{cfg.script_name}.json"

def _watermarks_file(cfg: TrackerConfig) -> Path:
    return STATE_DIR / f"last_seen_by_journal_{cfg.script_name}.json"

def _issue_state_file(cfg: TrackerConfig) -> Path:
    return STATE_DIR / f"last_seen_issues_{cfg.script_name}.json"


# ── 缓存读写 ───────────────────────────────────────────────────────────────────

def load_seen(cfg: TrackerConfig) -> set:
    f = _seen_file(cfg)
    return set(json.loads(f.read_text())) if f.exists() else set()

def save_seen(cfg: TrackerConfig, seen: set):
    _seen_file(cfg).write_text(json.dumps(sorted(seen), indent=2, ensure_ascii=False))

def load_fail_counts(cfg: TrackerConfig) -> dict:
    f = _fail_counts_file(cfg)
    return json.loads(f.read_text()) if f.exists() else {}

def save_fail_counts(cfg: TrackerConfig, counts: dict):
    _fail_counts_file(cfg).write_text(json.dumps(counts, indent=2, ensure_ascii=False))

def load_journal_watermarks(cfg: TrackerConfig) -> dict:
    f = _watermarks_file(cfg)
    return json.loads(f.read_text()) if f.exists() else {}

def save_journal_watermarks(cfg: TrackerConfig, data: dict):
    _watermarks_file(cfg).write_text(json.dumps(data, indent=2, ensure_ascii=False))

def load_issue_state(cfg: TrackerConfig) -> dict:
    f = _issue_state_file(cfg)
    return json.loads(f.read_text()) if f.exists() else {}

def save_issue_state(cfg: TrackerConfig, state: dict):
    _issue_state_file(cfg).write_text(json.dumps(state, indent=2, ensure_ascii=False))


# ── 水位更新 ───────────────────────────────────────────────────────────────────

def _max_date_in_items(items: list) -> str:
    max_date = ""
    for a in items:
        # 兼容 date_key（yin）和 date 字段
        raw = a.get("date_key") or a.get("date", "")
        m = re.search(r"\b\d{4}-\d{2}-\d{2}\b", raw)
        if m:
            d = m.group(0)
            if d > max_date:
                max_date = d
    return max_date

def update_journal_watermarks(cfg: TrackerConfig, articles: dict):
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    all_names = [n for n, _ in cfg.journals] + [n for n, _ in cfg.crossref_journals]
    crossref_names = {n for n, _ in cfg.crossref_journals}
    watermarks = load_journal_watermarks(cfg)
    for name in all_names:
        prev = watermarks.get(name, {})
        new_items = articles.get(name, [])
        new_count = len(new_items)
        max_date = prev.get("last_article_date", "")
        if new_count > 0:
            run_max = _max_date_in_items(new_items)
            if run_max and run_max > max_date:
                max_date = run_max
        watermarks[name] = {
            "source": "crossref" if name in crossref_names else "rss",
            "last_run_utc": now_utc,
            "new_count": new_count,
            "last_article_date": max_date,
            "last_updated_run_utc": now_utc if new_count > 0 else prev.get("last_updated_run_utc", ""),
        }
    save_journal_watermarks(cfg, watermarks)


# ── 摘要判断与补充 ─────────────────────────────────────────────────────────────

def _is_real_abstract(text: str, extra_filter: Callable[[str], bool] | None = None) -> bool:
    if not text:
        return False
    if text.startswith("Publication date:"):
        return False
    if len(text) < 100:
        return False
    if re.search(r'\b(EarlyView|Ahead of Print)\b', text):
        return False
    # 预设级额外过滤（如 huang 的 PNAS 规则）
    if extra_filter is not None and not extra_filter(text):
        return False
    return True

def _extract_doi(url: str) -> str:
    m = re.search(r'(10\.\d{4,}/[^\s&?#"<>]+)', url)
    return m.group(1).rstrip('.,;)') if m else ""

def _reconstruct_abstract(inverted_index: dict) -> str:
    if not inverted_index:
        return ""
    words: dict[int, str] = {}
    for word, positions in inverted_index.items():
        for pos in positions:
            words[pos] = word
    return " ".join(words[i] for i in sorted(words))

def enrich_abstracts(articles: dict, extra_filter: Callable[[str], bool] | None = None):
    missing = [
        (j, i) for j, items in articles.items()
        for i, a in enumerate(items)
        if not _is_real_abstract(a["abstract"], extra_filter)
        and "sciencedirect.com" not in a.get("link", "")
    ]
    if not missing:
        print("  摘要补充：无需补充")
        return
    print(f"  摘要补充：对 {len(missing)} 篇文章查询 OpenAlex + Semantic Scholar...")
    headers = {"User-Agent": "journal-tracker/1.0 (mailto:research@example.com)"}
    oa_n, ss_n = 0, 0
    for journal, idx in missing:
        articles[journal][idx]["abstract"] = ""
        a = articles[journal][idx]
        abstract = ""
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
            if not abstract:
                try:
                    url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}?fields=abstract"
                    with urllib.request.urlopen(
                        urllib.request.Request(url, headers=headers), timeout=10
                    ) as resp:
                        abstract = json.loads(resp.read()).get("abstract") or ""
                except Exception:
                    pass
                time.sleep(0.5)
                if abstract:
                    ss_n += 1
            else:
                oa_n += 1
        if abstract:
            articles[journal][idx]["abstract"] = abstract
    still = len(missing) - oa_n - ss_n
    print(f"  摘要补充完成：{oa_n} 篇来自 OpenAlex，{ss_n} 篇来自 Semantic Scholar，{still} 篇未能补充")


# ── 抓取 RSS ───────────────────────────────────────────────────────────────────

def fetch_rss(cfg: TrackerConfig, seen: set, exclude_names=None) -> tuple:
    results, errors = {}, {}
    cutoff = datetime.now(timezone.utc) - timedelta(days=21)
    excluded = set(exclude_names or [])
    for name, url in cfg.journals:
        if name in excluded:
            continue
        try:
            feed = feedparser.parse(url)
            new_items = []
            for entry in feed.entries:
                uid = entry.get("id") or entry.get("link", "")
                if not uid or uid in seen:
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
                if "sciencedirect.com" in entry.get("link", ""):
                    if not authors:
                        m = re.search(r'Author\(s\):\s*(.+?)$', summary, re.MULTILINE)
                        if m:
                            authors = m.group(1).strip()
                    if not pub_str:
                        m = re.search(r'Publication date:\s*(.+?)Source:', summary)
                        if m:
                            pub_str = m.group(1).strip()
                item = {
                    "title":    entry.get("title", "(no title)").strip(),
                    "link":     entry.get("link", "").replace("?af=R", ""),
                    "authors":  authors,
                    "abstract": summary,
                    "date":     pub_str,
                    "date_display": pub_str,
                    "date_key": pub_str,
                    "uid":      uid,
                    "doi":      entry.get("prism_doi", ""),
                }
                # 预设级扩展（如 yin 的 NBER 过滤/解析）
                if cfg.per_entry_transform is not None:
                    item = cfg.per_entry_transform(entry, item)
                    if item is None:
                        continue
                new_items.append(item)
            if new_items:
                results[name] = new_items
                print(f"  {name}: {len(new_items)} 篇")
            else:
                print(f"  {name}: 无新文章")
        except Exception as e:
            errors[name] = str(e)
            print(f"  {name}: ERROR - {e}")
    return results, errors


# ── 抓取 CrossRef ──────────────────────────────────────────────────────────────

def fetch_crossref(cfg: TrackerConfig, seen: set, exclude_names=None) -> tuple:
    results, errors = {}, {}
    from_date = (datetime.now(timezone.utc) - timedelta(days=21)).strftime("%Y-%m-%d")
    excluded = set(exclude_names or [])
    for name, issn in cfg.crossref_journals:
        if name in excluded:
            continue
        try:
            url = (
                f"https://api.crossref.org/journals/{issn}/works"
                f"?sort=published&order=desc&rows=50"
                f"&filter=from-pub-date:{from_date}"
                f"&select=DOI,title,author,published,abstract,URL"
            )
            req = urllib.request.Request(
                url, headers={"User-Agent": "journal-tracker/1.0 (mailto:research@example.com)"}
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
                if len(pd) >= 3:
                    date_display = pub_str
                elif len(pd) == 2:
                    try:
                        date_display = datetime(pd[0], pd[1], 1).strftime("%B %Y")
                    except (ValueError, TypeError):
                        date_display = pub_str
                else:
                    date_display = pub_str
                new_items.append({
                    "title": title, "link": link, "authors": authors,
                    "abstract": abstract, "date": pub_str,
                    "date_display": date_display, "date_key": pub_str,
                    "uid": uid,
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


# ── Issue 目录追踪 ─────────────────────────────────────────────────────────────

def fetch_new_issues(cfg: TrackerConfig, seen: set, public_issue_payload=None) -> tuple:
    state = load_issue_state(cfg)
    if public_issue_payload is None:
        public_issue_payload, _ = top5_tracker.fetch_top5_latest_issues()
    tracked_names = (
        {n for n, _ in cfg.journals} | {n for n, _ in cfg.crossref_journals}
    ) & top5_tracker.TOP5_JOURNAL_NAMES
    return top5_tracker.select_issue_sections(
        public_issue_payload, seen, state, allowed_names=tracked_names
    )


# ── HTML 渲染 ──────────────────────────────────────────────────────────────────

def _shorten(text: str, max_len: int = 420) -> str:
    if not text or len(text) <= max_len:
        return text or ""
    return text[:max_len].rstrip() + "..."

def _strip_html_tags(value: str) -> str:
    return re.sub(r"<[^>]+>", "", "" if value is None else str(value)).strip()

def _html_text(value: str, max_len=None) -> str:
    text = _strip_html_tags(value)
    if max_len is not None:
        text = _shorten(text, max_len)
    return html.escape(text, quote=False)

def _html_attr(value: str) -> str:
    return html.escape("" if value is None else str(value), quote=True)

def build_html(
    articles: dict,
    week_str: str,
    extra_filter: Callable[[str], bool] | None = None,
    issue_sections: dict = None,
) -> str:
    total = sum(len(v) for v in articles.values())
    sections = ""
    for journal, items in articles.items():
        with_abs    = [a for a in items if _is_real_abstract(a.get("abstract", ""), extra_filter)]
        without_abs = [a for a in items if not _is_real_abstract(a.get("abstract", ""), extra_filter)]
        rows = ""
        for a in with_abs + without_abs:
            title    = _html_text(a.get("title", "(no title)"))
            link     = _html_attr(a.get("link", ""))
            # date_display 优先，回退到 date（兼容旧缓存和未设置 date_display 的文章）
            date_str = _html_text(a.get("date_display") or a.get("date", ""))
            authors  = _html_text(a.get("authors", ""), max_len=420)
            abstract = (
                _html_text(a.get("abstract", ""))
                if _is_real_abstract(a.get("abstract", ""), extra_filter) else ""
            )
            rows += f"""
            <tr>
              <td style="padding:14px 0 18px 0; vertical-align:top;">
                <div style="font-size:17px; line-height:1.35; font-weight:700; color:#111827;">
                  <a href="{link}" style="color:#111827; text-decoration:none;">{title}</a>
                </div>
                {"<div style='font-size:15px; color:#1f2937; font-weight:500; line-height:1.45; margin:9px 0 0 0;'>" + authors + "</div>" if authors else ""}
                <div style="font-size:14px; color:#6b7280; margin:7px 0 0 0;">
                  {date_str + " | " if date_str else ""}<a href="{link}" style="color:#2563eb; text-decoration:underline;">Full article</a>
                </div>
                {"<div style='font-size:15px; color:#1f2937; line-height:1.65; margin:10px 0 0 0;'>" + abstract + "</div>" if abstract else ""}
              </td>
            </tr>"""
        journal_name = _html_text(journal)
        anchor = _html_attr("journal-" + re.sub(r"[^a-z0-9]+", "-", journal.lower()).strip("-"))
        no_abs_note = ""
        if without_abs:
            no_abs_note = (
                f'<div style="font-size:14px; color:#6b7280; line-height:1.45; margin:-8px 0 18px 0;">'
                f'{len(without_abs)} article{"s" if len(without_abs) != 1 else ""} in this journal do not provide abstracts via RSS.'
                f'</div>'
            )
        sections += f"""
        <div id="{anchor}" style="margin:46px 0 14px 0;">
          <h2 style="font-size:20px; color:#111827; letter-spacing:1.2px; text-transform:uppercase;
                     border-top:3px solid #111827; border-bottom:1px solid #9ca3af; padding:14px 0 11px 0;
                     margin:0 0 20px 0; font-weight:900;">{journal_name}
            <span style="font-weight:500; font-size:15px; color:#4b5563; letter-spacing:0; text-transform:none;">({len(items)} articles)</span>
          </h2>
          {no_abs_note}
          <table width="100%" cellpadding="0" cellspacing="0">{rows}</table>
        </div>"""

    issue_html = ""
    if issue_sections:
        issue_blocks = ""
        for jname, info in issue_sections.items():
            vol, iss = info["volume"], info["issue"]
            jname_esc = _html_text(jname)
            rows_i = ""
            for a in info["articles"]:
                title   = _html_text(a.get("title", "(no title)"))
                link    = _html_attr(a.get("link", ""))
                authors = _html_text(a.get("authors", ""), max_len=300)
                date_i  = _html_text(a.get("date", ""))
                if a.get("previously_sent"):
                    rows_i += f"""
            <tr>
              <td style="padding:10px 0 14px 0; vertical-align:top; color:#6b7280;">
                <span style="font-size:13px; margin-right:6px;">○</span>
                <span style="font-size:16px; font-weight:600;">
                  <a href="{link}" style="color:#6b7280; text-decoration:none;">{title}</a>
                </span>
                {"<div style='font-size:14px; margin:5px 0 0 20px;'>" + authors + "</div>" if authors else ""}
                <div style="font-size:13px; margin:4px 0 0 20px;">
                  {date_i + " | " if date_i else ""}<a href="{link}" style="color:#9ca3af; text-decoration:underline;">Full article</a>
                  <span style="margin-left:8px; font-style:italic;">Appeared in a previous digest</span>
                </div>
              </td>
            </tr>"""
                else:
                    rows_i += f"""
            <tr>
              <td style="padding:10px 0 14px 0; vertical-align:top;">
                <span style="font-size:13px; margin-right:6px; color:#2563eb;">●</span>
                <span style="font-size:16px; font-weight:700; color:#111827;">
                  <a href="{link}" style="color:#111827; text-decoration:none;">{title}</a>
                </span>
                {"<div style='font-size:14px; color:#1f2937; font-weight:500; margin:5px 0 0 20px;'>" + authors + "</div>" if authors else ""}
                <div style="font-size:13px; color:#6b7280; margin:4px 0 0 20px;">
                  {date_i + " | " if date_i else ""}<a href="{link}" style="color:#2563eb; text-decoration:underline;">Full article</a>
                </div>
              </td>
            </tr>"""
            issue_blocks += f"""
        <div style="margin:32px 0 14px 0;">
          <h3 style="font-size:17px; color:#111827; font-weight:800; margin:0 0 6px 0;">
            {jname_esc}
            <span style="font-weight:400; font-size:14px; color:#4b5563;"> · Volume {vol} Issue {iss}</span>
          </h3>
          <p style="font-size:13px; color:#6b7280; margin:0 0 12px 0;">
            ● First appearance &nbsp;·&nbsp; ○ Appeared in a previous digest
          </p>
          <table width="100%" cellpadding="0" cellspacing="0">{rows_i}</table>
        </div>"""
        issue_html = f"""
    <div style="margin-top:48px; padding-top:20px; border-top:3px solid #374151;">
      <h2 style="font-size:20px; color:#111827; font-weight:900; margin:0 0 6px 0;
                 letter-spacing:1px; text-transform:uppercase;">Latest Issue Digest</h2>
      <p style="font-size:14px; color:#6b7280; margin:0 0 4px 0;">
        The following journals published a new issue. Articles marked ● are new to this digest;
        articles marked ○ appeared in an earlier weekly digest.
      </p>
      {issue_blocks}
    </div>"""

    n_new_issues = len(issue_sections) if issue_sections else 0
    issue_note = (
        f" · {n_new_issues} journal{'s' if n_new_issues != 1 else ''} published a new issue"
        if n_new_issues else ""
    )
    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"></head>
<body style="margin:0; padding:0; background:#ffffff; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;">
  <div style="max-width:760px; margin:0 auto; padding:34px 42px 28px 42px; background:#ffffff;">
    <div style="padding:0 0 26px 0; margin-bottom:34px;">
      <h1 style="color:#111827; margin:0; font-size:26px; line-height:1.25; font-weight:800;">Journal Weekly Digest</h1>
      <p style="color:#4b5563; margin:8px 0 0; font-size:16px; line-height:1.45;">{week_str} · {total} new articles across {len(articles)} journals{issue_note}</p>
      <p style="margin:18px 0 0 0; font-size:15px; color:#374151; line-height:1.55;">Abstracts are included when available. Titles link to the full article pages.</p>
    </div>
    <div>{sections}</div>
    {issue_html}
    <div style="margin-top:32px; padding-top:14px; border-top:1px solid #e5e7eb; font-size:12px; color:#9ca3af;">
      Generated by journal-tracker · GitHub Actions
    </div>
  </div>
</body></html>"""


# ── 发送邮件 ───────────────────────────────────────────────────────────────────

def send_email(cfg: TrackerConfig, html_body: str, subject: str):
    sender    = os.environ["EMAIL_SENDER"]
    password  = os.environ["EMAIL_PASSWORD"]
    recipients = [r.strip() for r in os.environ[cfg.env_recipient].split(",")]
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = sender
    msg["To"]      = ", ".join(recipients)
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
        server.login(sender, password)
        server.sendmail(sender, recipients, msg.as_string())
    print(f"邮件已发送至 {', '.join(recipients)}")


def send_alert(cfg: TrackerConfig, triggered: dict):
    alert_recipient = os.environ.get("EMAIL_ALERT", "")
    if not alert_recipient:
        print("EMAIL_ALERT not configured, skipping alert.")
        return
    sender   = os.environ["EMAIL_SENDER"]
    password = os.environ["EMAIL_PASSWORD"]
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
    html_body = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"></head>
<body style="margin:0; padding:0; background:#f8fafc; font-family:-apple-system, Arial, sans-serif;">
  <div style="max-width:700px; margin:24px auto; background:#fff;
              border-radius:8px; overflow:hidden; box-shadow:0 1px 4px rgba(0,0,0,.08);">
    <div style="background:#dc2626; padding:24px 32px;">
      <h1 style="color:#fff; margin:0; font-size:20px;">Journal Tracker · RSS Alert</h1>
      <p style="color:#fecaca; margin:6px 0 0; font-size:13px;">
        脚本 <strong>{cfg.script_name}</strong> 中有 {n} 个期刊已连续 {FAIL_THRESHOLD} 周抓取失败
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
        在 <code>{cfg.script_name}.py</code> 中更新对应 URL 并提交。
      </p>
    </div>
    <div style="padding:16px 32px; background:#f1f5f9; font-size:11px; color:#94a3b8;">
      Generated by journal-tracker · GitHub Actions
    </div>
  </div>
</body></html>"""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[Journal Tracker · {cfg.script_name}] {n} journal{'s' if n > 1 else ''} failing for {FAIL_THRESHOLD}+ weeks"
    msg["From"]    = sender
    msg["To"]      = alert_recipient
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
        server.login(sender, password)
        server.sendmail(sender, [alert_recipient], msg.as_string())
    print(f"告警邮件已发送至 {alert_recipient}: {list(triggered.keys())}")


# ── 主流程 ────────────────────────────────────────────────────────────────────

def run_tracker(
    cfg: TrackerConfig,
    shared_top5_articles=None,
    shared_top5_article_errors=None,
    shared_top5_issues=None,
):
    test_mode    = "--test" in sys.argv
    preview_mode = "--preview" in sys.argv   # 全量抓取，生成本地HTML，不发信，不写缓存
    week_str  = datetime.now(timezone.utc).strftime("Week of %Y-%m-%d")
    issue_num = (datetime.now(timezone.utc).date() - cfg.start_date).days // 7 + 1
    if preview_mode:
        mode_label = "【预览模式·全量】"
    elif test_mode:
        mode_label = "【测试模式·全量】"
    else:
        mode_label = "【增量模式】"
    print(f"=== {cfg.script_name} tracker · {week_str} · 第{issue_num}期 · {mode_label} ===")

    seen        = set() if (test_mode or preview_mode) else load_seen(cfg)
    fail_counts = load_fail_counts(cfg)
    print(f"已记录文章数: {len(seen)}")

    exclude_names = top5_tracker.TOP5_JOURNAL_NAMES
    articles, rss_errors  = fetch_rss(cfg, seen, exclude_names=exclude_names)
    cr_results, cr_errors = fetch_crossref(cfg, seen, exclude_names=exclude_names)
    articles.update(cr_results)

    if shared_top5_articles is None:
        shared_top5_articles, shared_top5_article_errors = top5_tracker.fetch_top5_recent_articles()
    articles.update(
        top5_tracker.select_new_articles(
            shared_top5_articles, seen, allowed_names=top5_tracker.TOP5_JOURNAL_NAMES
        )
    )

    enrich_abstracts(articles, cfg.extra_abstract_filter)
    all_errors = {**rss_errors, **cr_errors, **(shared_top5_article_errors or {})}

    if not test_mode and not preview_mode:
        all_names = [n for n, _ in cfg.journals] + [n for n, _ in cfg.crossref_journals]
        for name in all_names:
            fail_counts[name] = fail_counts.get(name, 0) + 1 if name in all_errors else 0
        save_fail_counts(cfg, fail_counts)
        triggered = {
            name: (all_errors[name], fail_counts[name])
            for name in all_errors
            if fail_counts[name] == FAIL_THRESHOLD
        }
        if triggered:
            send_alert(cfg, triggered)

    total = sum(len(v) for v in articles.values())
    print(f"本次获取文章: {total} 篇（共 {len(articles)} 个期刊有更新）")
    if not test_mode and not preview_mode:
        update_journal_watermarks(cfg, articles)

    print("检测最新 Issue 目录...")
    issue_sections, new_issue_seen, updated_issue_state = fetch_new_issues(
        cfg, seen, public_issue_payload=shared_top5_issues
    )

    if total == 0 and not issue_sections:
        print("无新内容，跳过发送。")
        return

    html_body = build_html(
        articles, week_str,
        extra_filter=cfg.extra_abstract_filter,
        issue_sections=issue_sections,
    )

    if preview_mode:
        out_path = Path(__file__).resolve().parent / f"preview_{cfg.script_name}.html"
        out_path.write_text(html_body, encoding="utf-8")
        print(f"预览模式：HTML 已写入 {out_path}，未发送邮件，缓存未更新。")
    elif test_mode:
        subject = f"测试 · 第{issue_num}期 · Journal Weekly Digest · {total} articles — {week_str}"
        send_email(cfg, html_body, subject)
        print("测试完成，缓存未更新。")
    else:
        subject = f"第{issue_num}期 · Journal Weekly Digest · {total} new articles — {week_str}"
        for items in articles.values():
            for a in items:
                seen.add(a["uid"])
        seen |= new_issue_seen
        save_seen(cfg, seen)
        save_issue_state(cfg, updated_issue_state)
        send_email(cfg, html_body, subject)
        print("完成，缓存已更新。")
