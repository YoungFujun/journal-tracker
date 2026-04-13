"""
catchup.py — 一次性补发脚本
补发2026年3月1日至3月29日因 RSS 抓取问题遗漏的文章。

背景：早期版本窗口为7天，OUP 期刊为静态当期 RSS，AJS RSS 同类问题，
导致 3月期间部分文章被遗漏。本脚本为一次性补发，运行后请删除。

用法：
  正常补发（写入缓存）:  python catchup.py
  测试（不写缓存）:      python catchup.py --test
"""

import os
import sys
import json
import re
import time
import smtplib
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta, date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

# ── 补发时间范围 ──────────────────────────────────────────────────────────────
FROM_DATE = "2026-03-01"
TO_DATE   = "2026-03-29"   # 含当天

# ── 各收件人期刊配置（全部通过 CrossRef 抓取）────────────────────────────────
# CrossRef 覆盖所有期刊（包含原 RSS 期刊），无需区分来源
RECIPIENT_CONFIGS = [
    {
        "name":      "journal_tracker",
        "seen_file": Path("seen_articles.json"),
        "recipient": os.environ["EMAIL_RECIPIENT"],
        "journals": [
            ("Journal of Political Economy",          "0022-3808"),
            ("The Quarterly Journal of Economics",    "0033-5533"),
            ("The Review of Economic Studies",        "0034-6527"),
            ("Review of Financial Studies",           "0893-9454"),
        ],
    },
    {
        "name":      "yifanxu",
        "seen_file": Path("seen_yifanxu.json"),
        "recipient": os.environ["EMAIL_RECIPIENT_YIFAN"],
        "journals": [
            ("Journal of Political Economy",          "0022-3808"),
            ("The Quarterly Journal of Economics",    "0033-5533"),
            ("The Review of Economic Studies",        "0034-6527"),
        ],
    },
    {
        "name":      "haihuang",
        "seen_file": Path("seen_haihuang.json"),
        "recipient": os.environ["EMAIL_RECIPIENT_HAIHUANG"],
        "journals": [
            ("Journal of Political Economy",          "0022-3808"),
            ("The Quarterly Journal of Economics",    "0033-5533"),
            ("The Review of Economic Studies",        "0034-6527"),
            ("Review of Financial Studies",           "0893-9454"),
            ("American Journal of Sociology",         "0002-9602"),
        ],
    },
    {
        "name":      "jiahuitan",
        "seen_file": Path("seen_jiahuitan.json"),
        "recipient": os.environ["EMAIL_RECIPIENT_JIAHUITAN"],
        "journals": [
            ("Journal of Political Economy",          "0022-3808"),
            ("The Quarterly Journal of Economics",    "0033-5533"),
            ("The Review of Economic Studies",        "0034-6527"),
        ],
    },
]

# ── 配置 ─────────────────────────────────────────────────────────────────────
SMTP_HOST = "smtp.163.com"
SMTP_PORT = 465
SENDER    = os.environ["EMAIL_SENDER"]
PASSWORD  = os.environ["EMAIL_PASSWORD"]

TEST_MODE = "--test" in sys.argv


# ── 缓存读写 ──────────────────────────────────────────────────────────────────
def load_seen(path: Path) -> set:
    if path.exists():
        return set(json.loads(path.read_text()))
    return set()


def save_seen(path: Path, seen: set):
    path.write_text(json.dumps(sorted(seen), indent=2, ensure_ascii=False))


# ── CrossRef 抓取 ─────────────────────────────────────────────────────────────
def fetch_missed_articles(journals: list, seen: set) -> dict:
    results = {}
    for name, issn in journals:
        url = (f"https://api.crossref.org/journals/{issn}/works"
               f"?sort=published&order=desc&rows=50"
               f"&filter=from-pub-date:{FROM_DATE},until-pub-date:{TO_DATE}"
               f"&select=DOI,title,author,published,abstract,URL")
        req = urllib.request.Request(
            url, headers={"User-Agent": "journal-tracker/1.0 (mailto:research@example.com)"}
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read())
            items = data.get("message", {}).get("items", [])
            new_items = []
            for item in items:
                uid = item.get("DOI", "")
                if not uid or uid in seen:
                    continue
                title = " ".join(item.get("title", ["(no title)"]))
                # 过滤纯行政条目
                if any(kw in title for kw in ["Front Matter", "Back Matter", "Turnaround Times",
                                               "Recent Referees", "JPE Turnaround", "Expression of Concern"]):
                    continue
                link    = item.get("URL") or f"https://doi.org/{uid}"
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
                print(f"    {name}: {len(new_items)} missed articles found")
            else:
                print(f"    {name}: none missed (or all already sent)")
        except Exception as e:
            print(f"    {name}: ERROR - {e}")
    return results


# ── OpenAlex 摘要补充 ─────────────────────────────────────────────────────────
def _is_real_abstract(text: str) -> bool:
    if not text or len(text) < 100:
        return False
    if re.search(r'\b(EarlyView|Ahead of Print)\b', text):
        return False
    return True


def enrich_abstracts(articles: dict):
    missing = [(j, i) for j, items in articles.items()
               for i, a in enumerate(items) if not _is_real_abstract(a.get("abstract", ""))]
    if not missing:
        return
    print(f"    OpenAlex 补充摘要：{len(missing)} 篇...")
    headers = {"User-Agent": "journal-tracker/1.0 (mailto:research@example.com)"}
    enriched = 0
    for journal, idx in missing:
        articles[journal][idx]["abstract"] = ""
        doi = articles[journal][idx].get("uid", "")
        if doi:
            try:
                doi_url = urllib.parse.quote(f"https://doi.org/{doi}", safe="")
                url = f"https://api.openalex.org/works/{doi_url}?select=abstract_inverted_index"
                with urllib.request.urlopen(
                    urllib.request.Request(url, headers=headers), timeout=10
                ) as resp:
                    inv = json.loads(resp.read()).get("abstract_inverted_index")
                if inv:
                    words: dict[int, str] = {}
                    for word, positions in inv.items():
                        for pos in positions:
                            words[pos] = word
                    articles[journal][idx]["abstract"] = " ".join(words[i] for i in sorted(words))
                    enriched += 1
            except Exception:
                pass
            time.sleep(0.1)
    print(f"    摘要补充完成：{enriched}/{len(missing)}")


# ── 构建 HTML ─────────────────────────────────────────────────────────────────
def build_html(articles: dict) -> str:
    total = sum(len(v) for v in articles.values())
    sections = ""
    for journal, items in articles.items():
        with_abs    = [a for a in items if _is_real_abstract(a.get("abstract", ""))]
        without_abs = [a for a in items if not _is_real_abstract(a.get("abstract", ""))]
        rows = ""
        for a in with_abs:
            rows += f"""
            <tr>
              <td style="padding:10px 0; border-bottom:1px solid #eee; vertical-align:top;">
                <div style="font-size:15px; font-weight:600; margin-bottom:4px;">
                  <a href="{a['link']}" style="color:#1a56db; text-decoration:none;">{a['title']}</a>
                </div>
                {"<div style='font-size:12px; color:#888; margin-bottom:2px;'>" + a['date'] + "</div>" if a['date'] else ""}
                {"<div style='font-size:12px; color:#666; margin-bottom:4px;'>" + a['authors'] + "</div>" if a['authors'] else ""}
                <div style="background:#f1f5f9; border-radius:4px; padding:8px 12px; margin-top:4px;">
                  <div style="font-size:12px; color:#444; line-height:1.5;">{a['abstract']}</div>
                </div>
              </td>
            </tr>"""
        if without_abs:
            rows += f"""
            <tr>
              <td style="padding:{'14px' if with_abs else '4px'} 0 6px 0;">
                <div style="font-size:11px; color:#94a3b8; font-style:italic;">Abstract not provided — click the title to read the full article.</div>
              </td>
            </tr>"""
            for a in without_abs:
                rows += f"""
            <tr>
              <td style="padding:8px 0; border-bottom:1px solid #eee; vertical-align:top;">
                <div style="font-size:15px; font-weight:600; margin-bottom:4px;">
                  <a href="{a['link']}" style="color:#1a56db; text-decoration:none;">{a['title']}</a>
                </div>
                {"<div style='font-size:12px; color:#888; margin-bottom:2px;'>" + a['date'] + "</div>" if a['date'] else ""}
                {"<div style='font-size:12px; color:#666;'>" + a['authors'] + "</div>" if a['authors'] else ""}
              </td>
            </tr>"""
        sections += f"""
        <div style="margin-bottom:28px;">
          <h2 style="font-size:17px; color:#1e293b; background:#f0f4ff;
                     border-left:5px solid #1a56db; padding:10px 14px;
                     margin:0 0 14px 0; border-radius:0 4px 4px 0;">{journal}
            <span style="font-weight:normal; font-size:13px; color:#64748b;">({len(items)} articles)</span>
          </h2>
          <table width="100%" cellpadding="0" cellspacing="0">{rows}</table>
        </div>"""

    notice = """
        <div style="background:#fef9ec; border:1px solid #f59e0b; border-radius:6px;
                    padding:14px 18px; margin-bottom:28px; font-size:13px; color:#78350f; line-height:1.6;">
          <strong>说明：</strong>本邮件为一次性补发。由于早期抓取程序对 OUP 等出版商 RSS 兼容性不足，
          以下文章（发表于 2026-03-01 至 2026-03-29）在前三期每周推送中被遗漏。
          已修复相关问题，后续周报将正常运行。
        </div>"""

    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"></head>
<body style="margin:0; padding:0; background:#f8fafc; font-family: -apple-system, Arial, sans-serif;">
  <div style="max-width:700px; margin:24px auto; background:#fff;
              border-radius:8px; overflow:hidden; box-shadow:0 1px 4px rgba(0,0,0,.08);">
    <div style="background:#7c3aed; padding:24px 32px;">
      <h1 style="color:#fff; margin:0; font-size:20px;">📚 Journal Digest · 补发</h1>
      <p style="color:#ddd6fe; margin:6px 0 0; font-size:13px;">
        2026-03-01 to 2026-03-29 · {total} missed articles across {len(articles)} journals
      </p>
    </div>
    <div style="padding:24px 32px;">{notice}{sections}</div>
    <div style="padding:16px 32px; background:#f1f5f9; font-size:11px; color:#94a3b8;">
      Generated by journal-tracker · Catch-up run (one-time)
    </div>
  </div>
</body></html>"""


# ── 发送邮件 ──────────────────────────────────────────────────────────────────
def send_email(html: str, subject: str, recipient: str):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = SENDER
    msg["To"]      = recipient
    msg.attach(MIMEText(html, "html", "utf-8"))
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
        server.login(SENDER, PASSWORD)
        server.sendmail(SENDER, [recipient], msg.as_string())
    print(f"    Email sent to {recipient}")


# ── 主流程 ────────────────────────────────────────────────────────────────────
def main():
    mode = "【测试模式·不写缓存】" if TEST_MODE else "【正式补发·写入缓存】"
    print(f"=== Journal Tracker · 补发脚本 · {FROM_DATE} to {TO_DATE} · {mode} ===\n")

    for config in RECIPIENT_CONFIGS:
        name      = config["name"]
        seen_file = config["seen_file"]
        recipient = config["recipient"]
        journals  = config["journals"]
        print(f"[{name}] recipient: {recipient}")

        seen = load_seen(seen_file)
        print(f"  Seen cache: {len(seen)} entries")

        missed = fetch_missed_articles(journals, seen)
        enrich_abstracts(missed)

        total = sum(len(v) for v in missed.values())
        if total == 0:
            print(f"  Nothing to send for {name}.\n")
            continue

        html    = build_html(missed)
        subject = f"查漏补缺 · Journal Weekly Digest · {total} articles — 2026-03（第1–3期遗漏）"
        if TEST_MODE:
            subject = f"测试 · {subject}"
            print(f"  TEST MODE: would send {total} articles, not writing cache.")
        else:
            send_email(html, subject, recipient)
            for items in missed.values():
                for a in items:
                    seen.add(a["uid"])
            save_seen(seen_file, seen)
            print(f"  Cache updated: {len(seen)} entries.")
        print()


if __name__ == "__main__":
    main()
