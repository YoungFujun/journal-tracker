import html
import http.client
import json
import os
import re
import smtplib
import ssl
import sys
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import List


ROOT = Path(__file__).resolve().parent
STATE_DIR = ROOT / "state"
SMTP_HOST = "smtp.163.com"
SMTP_PORT = 465
USER_AGENT = "journal-tracker-special/1.0 (mailto:research@example.com)"

ISSUE_TRACKED_JOURNALS = [
    ("American Economic Review", "0002-8282"),
    ("The Quarterly Journal of Economics", "0033-5533"),
    ("Journal of Political Economy", "0022-3808"),
    ("Econometrica", "0012-9682"),
    ("The Review of Economic Studies", "0034-6527"),
]

SKIP_TITLE_PATTERNS = re.compile(
    r"\b(front\s*matter|back\s*matter|backmatter|frontmatter|erratum|corrigendum"
    r"|turnaround\s*time|recent\s*refer|acknowledgment|election\s*of\s*fellow"
    r"|annual\s*report|report\s*of\s*the\s*secretary|report\s*of\s*the\s*treasurer)\b",
    re.IGNORECASE,
)


@dataclass
class Audience:
    name: str
    recipient_env: str
    seen_file: Path


AUDIENCES = [
    Audience("main", "EMAIL_RECIPIENT", STATE_DIR / "seen_articles.json"),
    Audience("yifanxu", "EMAIL_RECIPIENT_YIFAN", STATE_DIR / "seen_yifanxu.json"),
    Audience("haihuang", "EMAIL_RECIPIENT_HAIHUANG", STATE_DIR / "seen_haihuang.json"),
    Audience("jiahuitan", "EMAIL_RECIPIENT_JIAHUITAN", STATE_DIR / "seen_jiahuitan.json"),
    Audience("shangyin", "EMAIL_RECIPIENT_SHANGYIN", STATE_DIR / "seen_shangyin.json"),
]


def install_unverified_ssl():
    ssl._create_default_https_context = ssl._create_unverified_context
    handler = urllib.request.HTTPSHandler(context=ssl._create_unverified_context())
    urllib.request.install_opener(urllib.request.build_opener(handler))


def load_seen(path: Path) -> set:
    if path.exists():
        return set(json.loads(path.read_text()))
    return set()


def fetch_json(url: str, retries: int = 5, base_sleep: float = 2.0):
    last_error = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=25) as resp:
                return json.loads(resp.read())
        except Exception as e:
            last_error = e
            retryable = (
                "429" in str(e)
                or isinstance(e, http.client.RemoteDisconnected)
                or "timed out" in str(e).lower()
            )
            if retryable and attempt < retries - 1:
                time.sleep(base_sleep * (attempt + 1))
                continue
            raise last_error
    raise last_error


def detect_latest_issue(issn: str):
    url = (
        f"https://api.crossref.org/journals/{issn}/works"
        f"?sort=published&order=desc&rows=80"
        f"&select=DOI,title,author,abstract,published,volume,issue,URL"
        f"&filter=type:journal-article"
    )
    items = fetch_json(url).get("message", {}).get("items", [])
    latest_vol, latest_iss = None, None
    for item in items:
        vol = str(item.get("volume", "")).strip()
        iss = str(item.get("issue", "")).strip()
        if not vol or not iss:
            continue
        if latest_vol is None:
            latest_vol, latest_iss = vol, iss
            continue
        try:
            if int(vol) > int(latest_vol) or (vol == latest_vol and int(iss) > int(latest_iss)):
                latest_vol, latest_iss = vol, iss
        except ValueError:
            pass
    return latest_vol, latest_iss


def fetch_issue_articles(issn: str, volume: str, issue: str):
    url = (
        f"https://api.crossref.org/journals/{issn}/works"
        f"?sort=published&order=desc&rows=300"
        f"&select=DOI,title,author,abstract,published,volume,issue,URL"
        f"&filter=type:journal-article"
    )
    items = fetch_json(url).get("message", {}).get("items", [])
    results = []
    for item in items:
        if str(item.get("volume", "")).strip() != volume or str(item.get("issue", "")).strip() != issue:
            continue
        title = " ".join(item.get("title", ["(no title)"])).strip()
        if not title or SKIP_TITLE_PATTERNS.search(title):
            continue
        doi = item.get("DOI", "").strip()
        link = item.get("URL") or (f"https://doi.org/{doi}" if doi else "")
        authors = ", ".join(
            f"{a.get('given', '')} {a.get('family', '')}".strip()
            for a in item.get("author", [])[:5]
        )
        pd = item.get("published", {}).get("date-parts", [[]])[0]
        pub_str = "-".join(str(p).zfill(2) for p in pd) if pd else ""
        results.append({
            "title": title,
            "link": link,
            "authors": authors,
            "date": pub_str,
            "doi": doi,
        })
    return results


def fetch_latest_issue_payload():
    payload = {}
    for name, issn in ISSUE_TRACKED_JOURNALS:
        try:
            volume, issue = detect_latest_issue(issn)
            if not volume or not issue:
                continue
            articles = fetch_issue_articles(issn, volume, issue)
            if articles:
                payload[name] = {
                    "volume": volume,
                    "issue": issue,
                    "articles": articles,
                }
        except Exception as e:
            print(f"[warn] failed to fetch {name}: {e}")
    return payload


def mark_previously_sent(base_payload: dict, seen: set):
    payload = {}
    for journal, info in base_payload.items():
        marked_articles = []
        for article in info["articles"]:
            doi = article.get("doi", "")
            doi_lower = doi.lower()
            previously_sent = (
                doi in seen
                or doi_lower in seen
                or any(doi_lower in s.lower() for s in seen if doi_lower)
            )
            marked = dict(article)
            marked["previously_sent"] = previously_sent
            marked_articles.append(marked)
        payload[journal] = {
            "volume": info["volume"],
            "issue": info["issue"],
            "articles": marked_articles,
        }
    return payload


def build_issue_digest_html(issue_sections: dict):
    blocks = []
    for journal, info in issue_sections.items():
        rows = []
        for article in info["articles"]:
            title = html.escape(article["title"], quote=False)
            link = html.escape(article["link"], quote=True)
            authors = html.escape(article.get("authors", ""), quote=False)
            date = html.escape(article.get("date", ""), quote=False)
            if article.get("previously_sent"):
                rows.append(
                    f"""
                    <tr>
                      <td style="padding:10px 0 14px 0; vertical-align:top; color:#6b7280;">
                        <span style="font-size:13px; margin-right:6px;">○</span>
                        <span style="font-size:16px; font-weight:600;">
                          <a href="{link}" style="color:#6b7280; text-decoration:none;">{title}</a>
                        </span>
                        {"<div style='font-size:14px; margin:5px 0 0 20px;'>" + authors + "</div>" if authors else ""}
                        <div style="font-size:13px; margin:4px 0 0 20px;">
                          {date + " | " if date else ""}<a href="{link}" style="color:#9ca3af; text-decoration:underline;">Full article</a>
                          <span style="margin-left:8px; font-style:italic;">Appeared in a previous digest</span>
                        </div>
                      </td>
                    </tr>
                    """
                )
            else:
                rows.append(
                    f"""
                    <tr>
                      <td style="padding:10px 0 14px 0; vertical-align:top;">
                        <span style="font-size:13px; margin-right:6px; color:#2563eb;">●</span>
                        <span style="font-size:16px; font-weight:700; color:#111827;">
                          <a href="{link}" style="color:#111827; text-decoration:none;">{title}</a>
                        </span>
                        {"<div style='font-size:14px; color:#1f2937; font-weight:500; margin:5px 0 0 20px;'>" + authors + "</div>" if authors else ""}
                        <div style="font-size:13px; color:#6b7280; margin:4px 0 0 20px;">
                          {date + " | " if date else ""}<a href="{link}" style="color:#2563eb; text-decoration:underline;">Full article</a>
                        </div>
                      </td>
                    </tr>
                    """
                )
        blocks.append(
            f"""
            <div style="margin:32px 0 14px 0;">
              <h3 style="font-size:17px; color:#111827; font-weight:800; margin:0 0 6px 0;">
                {html.escape(journal, quote=False)}
                <span style="font-weight:400; font-size:14px; color:#4b5563;"> · Volume {html.escape(info['volume'])} Issue {html.escape(info['issue'])}</span>
              </h3>
              <p style="font-size:13px; color:#6b7280; margin:0 0 12px 0;">
                ● First appearance &nbsp;·&nbsp; ○ Appeared in a previous digest
              </p>
              <table width="100%" cellpadding="0" cellspacing="0">{''.join(rows)}</table>
            </div>
            """
        )
    return "".join(blocks)


def build_email_html(subject: str, issue_sections: dict):
    intro = """
    <div style="margin:0 0 34px 0; font-size:15px; color:#1f2937; line-height:1.8;">
      <p style="margin:0 0 16px 0;">敬爱的朋友：</p>
      <p style="margin:0 0 16px 0;">这封邮件旨在补充整理 2026 年 4 月五大经济学期刊最新一期的目录内容，方便集中查看这些期次正式收录的文章。</p>
      <p style="margin:0 0 16px 0;">借此机会简要说明目前程序的抓取逻辑：现有周报主要按“近期新出现的文章”进行抓取和推送，文章一旦进入数据源并被识别到，便会在后续邮件中发送。由于五大刊的许多文章通常会先以提前发表的形式上线，之后才正式编入某一期目录，因此邮件中的文章更新时间与期刊最新一期目录的发布时间有时并不完全一致。也就是说，某篇文章可能已经在此前周报中出现，但在之后才被编入正式期次；反过来，某一期目录刚刚发布时，其中部分文章也未必都是第一次出现在邮件中。</p>
      <p style="margin:0 0 16px 0;">为使后续邮件的信息呈现更加完整，自下一期邮件起，程序将在原有周报基础上，新增五大刊最新一期目录的追加内容。当检测到五大刊发布新的正式期次时，邮件末尾将附上该期完整目录，并区分其中哪些文章此前已经推送过，哪些是首次出现在邮件中。这样既保留了常规周报的及时性，也便于大家从期次角度集中查看最新目录。</p>
      <p style="margin:0 0 16px 0;">目前，这一目录追加功能仅适用于 AER、QJE、JPE、Econometrica 和 REStud。其他期刊暂仍按照原有方式更新，暂不追加最新一期目录信息。</p>
      <p style="margin:0 0 16px 0;">如发现目录内容或文章链接存在明显问题，欢迎随时告知，我会继续完善相关规则。</p>
      <p style="margin:0;">敬礼！</p>
    </div>
    """
    digest = build_issue_digest_html(issue_sections)
    subtitle = "2026 年 4 月五大刊最新一期目录补充推送"
    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"></head>
<body style="margin:0; padding:0; background:#ffffff; font-family:-apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;">
  <div style="max-width:760px; margin:0 auto; padding:34px 42px 28px 42px; background:#ffffff;">
    <div style="padding:0 0 26px 0; margin-bottom:34px;">
      <h1 style="color:#111827; margin:0; font-size:26px; line-height:1.25; font-weight:800;">{html.escape(subject, quote=False)}</h1>
      <p style="color:#4b5563; margin:8px 0 0; font-size:16px; line-height:1.45;">{subtitle}</p>
    </div>
    {intro}
    <div style="margin-top:48px; padding-top:20px; border-top:3px solid #374151;">
      <h2 style="font-size:20px; color:#111827; font-weight:900; margin:0 0 6px 0; letter-spacing:1px; text-transform:uppercase;">Latest Issue Digest</h2>
      <p style="font-size:14px; color:#6b7280; margin:0 0 4px 0;">
        The following journals published a new issue. Articles marked ● are new to this digest; articles marked ○ appeared in an earlier weekly digest.
      </p>
      {digest}
    </div>
    <div style="margin-top:32px; padding-top:14px; border-top:1px solid #e5e7eb; font-size:12px; color:#9ca3af;">
      Generated by journal-tracker · special issue broadcast
    </div>
  </div>
</body></html>"""


def send_email(subject: str, html_body: str, recipients: List[str]):
    sender = os.environ["EMAIL_SENDER"]
    password = os.environ["EMAIL_PASSWORD"]
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
        server.login(sender, password)
        server.sendmail(sender, recipients, msg.as_string())


def main():
    install_unverified_ssl()
    send_mode = "--send" in sys.argv
    subject = "补充推送｜2026 年 4 月五大刊最新一期目录"
    base_payload = fetch_latest_issue_payload()
    summaries = []

    for audience in AUDIENCES:
        seen = load_seen(audience.seen_file)
        issue_sections = mark_previously_sent(base_payload, seen)
        html_body = build_email_html(subject, issue_sections)
        output_path = ROOT / "tmp" / f"special_issue_preview_{audience.name}.html"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(html_body, encoding="utf-8")

        recipient_value = os.environ.get(audience.recipient_env, "")
        recipients = [r.strip() for r in recipient_value.split(",") if r.strip()]
        issue_summary = {
            journal: {
                "count": len(info["articles"]),
                "previously_sent_count": sum(1 for a in info["articles"] if a["previously_sent"]),
            }
            for journal, info in issue_sections.items()
        }
        summaries.append({
            "audience": audience.name,
            "preview": str(output_path),
            "recipient_env": audience.recipient_env,
            "has_recipients": bool(recipients),
            "journals": issue_summary,
        })

        if send_mode:
            if not recipients:
                raise RuntimeError(f"Missing recipients for {audience.name}: {audience.recipient_env}")
            send_email(subject, html_body, recipients)

    print(json.dumps({
        "subject": subject,
        "send_mode": send_mode,
        "base_journals": {
            journal: {
                "volume": info["volume"],
                "issue": info["issue"],
                "count": len(info["articles"]),
            }
            for journal, info in base_payload.items()
        },
        "audiences": summaries,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
