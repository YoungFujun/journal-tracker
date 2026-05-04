"""
yin — 可选期刊预设
覆盖 Top 5 + 城市/区域经济 7 个来源。

用法：
  正常运行（增量，更新缓存）:  python yin.py
  测试运行（全量，不写缓存）:  python yin.py --test
  本地预览（生成HTML，不发信）: python yin.py --preview
"""

import re
import calendar
import urllib.request
from datetime import datetime, timezone, timedelta, date
from pathlib import Path
import tracker_core

JOURNALS = [
    # OUP 期刊（QJE、RES）改用 CrossRef，见下方
    ("Journal of Political Economy", "https://www.journals.uchicago.edu/action/showFeed?type=etoc&feed=rss&jc=jpe"),
    ("Econometrica", "https://onlinelibrary.wiley.com/feed/14680262/most-recent"),
    ("Journal of Urban Economics", "https://rss.sciencedirect.com/publication/science/00941190"),
    ("NBER Working Papers (Regional Economics)", "https://www.nber.org/rss/new.xml"),
]

# OUP RSS 为静态当期期号 feed，改用 CrossRef
CROSSREF_JOURNALS = [
    ("American Economic Review", "0002-8282"),
    ("The Quarterly Journal of Economics", "0033-5533"),
    ("The Review of Economic Studies", "0034-6527"),
]


# ── NBER 特有处理 ──────────────────────────────────────────────────────────────

def _is_nber_regional_working_paper(entry, title: str, summary: str) -> bool:
    text = f"{title} {summary}".lower()
    keywords = [
        "urban", "city", "cities", "metropolitan", "spatial",
        "agglomeration", "suburbanization", "sprawl", "density",
        "housing", "real estate", "land use", "zoning",
        "land value", "rent control", "gentrification",
        "commuting", "internal migration", "urban wage premium",
        "transportation infrastructure", "transit",
        "place-based", "local government", "intergovernmental",
        "regional", "economic geography", "quantitative spatial",
    ]
    is_wp = "/papers/w" in entry.get("link", "").lower()
    return is_wp and any(k in text for k in keywords)


def _split_nber_title_authors(title: str) -> tuple:
    """NBER RSS 把作者拼在标题后：Title -- by Author A, Author B。"""
    m = re.match(r"^(.*?)\s+--\s+by\s+(.+)$", title or "", flags=re.IGNORECASE)
    if not m:
        return title or "", ""
    return m.group(1).strip(), m.group(2).strip()


def _normalize_date_str(raw: str) -> str:
    """将常见日期文本标准化为 YYYY-MM-DD；无法解析则原样返回。"""
    s = (raw or "").strip()
    if not s:
        return ""
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        return s
    m = re.match(r"^(\d{4})/(\d{1,2})/(\d{1,2})$", s)
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    for fmt in ("%B %Y", "%b %Y"):
        try:
            dt = datetime.strptime(s, fmt)
            last_day = calendar.monthrange(dt.year, dt.month)[1]
            return f"{dt.year:04d}-{dt.month:02d}-{last_day:02d}"
        except ValueError:
            pass
    m = re.search(r"\b([A-Za-z]+)\s+(\d{4})\b", s)
    if m:
        for fmt in ("%B %Y", "%b %Y"):
            try:
                dt = datetime.strptime(f"{m.group(1)} {m.group(2)}", fmt)
                last_day = calendar.monthrange(dt.year, dt.month)[1]
                return f"{dt.year:04d}-{dt.month:02d}-{last_day:02d}"
            except ValueError:
                pass
    return s


def _fetch_nber_publication_date(link: str) -> str:
    """从 NBER 论文页面提取发布日期并返回 YYYY-MM-DD。"""
    if not link:
        return ""
    try:
        req = urllib.request.Request(
            link,
            headers={"User-Agent": "journal-tracker/1.0 (mailto:research@example.com)"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            page = resp.read().decode("utf-8", errors="ignore")
    except Exception:
        return ""
    for pat in (
        r'citation_publication_date"\s+content="([^"]+)"',
        r'property="article:published_time"\s+content="([^"]+)"',
        r'name="DC\.Date"\s+content="([^"]+)"',
    ):
        m = re.search(pat, page, re.IGNORECASE)
        if m:
            d = _normalize_date_str(m.group(1).strip())
            if re.match(r"^\d{4}-\d{2}-\d{2}$", d):
                return d
    m = re.search(r'Issue Date.*?<time\s+datetime="([^"]+)"', page, re.IGNORECASE | re.DOTALL)
    if m:
        d = _normalize_date_str(m.group(1)[:10])
        if re.match(r"^\d{4}-\d{2}-\d{2}$", d):
            return d
    m = re.search(r'Issue Date[^<]{0,80}([A-Za-z]+\s+\d{4})', page, re.IGNORECASE)
    if m:
        d = _normalize_date_str(m.group(1))
        if re.match(r"^\d{4}-\d{2}-\d{2}$", d):
            return d
    return ""


def _within_window(date_key: str, cutoff: datetime) -> bool:
    if not date_key:
        return True
    try:
        item_date = datetime.strptime(date_key[:10], "%Y-%m-%d")
    except ValueError:
        return True
    return item_date >= cutoff.replace(tzinfo=None)


def _yin_entry_transform(entry, item: dict) -> dict | None:
    """
    NBER 过滤和解析：仅保留区域经济相关 working paper，并修正标题、作者、日期字段。
    ScienceDirect 的月份粒度日期处理也在这里统一完成。
    非 NBER 条目直接透传。
    """
    name = None
    # 通过 link 判断是否 NBER
    link = item.get("link", "")
    is_nber = "nber.org" in link

    cutoff = datetime.now(timezone.utc) - timedelta(days=21)

    if is_nber:
        title_raw = entry.get("title", "")
        summary   = re.sub(r"<[^>]+>", "", entry.get("summary", "")).strip()
        if not _is_nber_regional_working_paper(entry, title_raw, summary):
            return None  # 不符合区域经济关键词，跳过

        nber_title, nber_authors = _split_nber_title_authors(title_raw)
        if nber_authors:
            item["authors"] = nber_authors
        item["title"] = nber_title

        pub_str = item.get("date", "")
        if not pub_str:
            pub_str = _fetch_nber_publication_date(link)
            if not pub_str:
                pub_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        date_key = _normalize_date_str(pub_str)

        if not _within_window(date_key, cutoff):
            return None

        try:
            dt = datetime.strptime(date_key[:7], "%Y-%m")
            date_display = dt.strftime("%B %Y")
        except ValueError:
            date_display = pub_str

        item["date"]         = pub_str
        item["date_key"]     = date_key
        item["date_display"] = date_display
        return item

    # ScienceDirect：月份粒度日期标准化
    if "sciencedirect.com" in link:
        pub_str = item.get("date", "")
        if pub_str:
            date_key = _normalize_date_str(pub_str)
            item["date_key"]     = date_key
            item["date_display"] = pub_str   # 保留原始"May 2026"格式
            if not _within_window(date_key, cutoff):
                return None

    return item


CONFIG = tracker_core.TrackerConfig(
    script_name="yin",
    start_date=date(2026, 4, 20),
    env_recipient="EMAIL_RECIPIENT_YIN",
    journals=JOURNALS,
    crossref_journals=CROSSREF_JOURNALS,
    per_entry_transform=_yin_entry_transform,
)


def main(shared_top5_articles=None, shared_top5_article_errors=None, shared_top5_issues=None):
    tracker_core.run_tracker(
        CONFIG, shared_top5_articles, shared_top5_article_errors, shared_top5_issues
    )


if __name__ == "__main__":
    main()
