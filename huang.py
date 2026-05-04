"""
huang — 可选期刊预设
覆盖经济/社会/政治/金融/经济史 26 个期刊。

用法：
  正常运行（增量，更新缓存）:  python huang.py
  测试运行（全量，不写缓存）:  python huang.py --test
  本地预览（生成HTML，不发信）: python huang.py --preview
"""

import re
from datetime import date
import tracker_core

JOURNALS = [
    # 社会学
    # AJS: Chicago etoc 为静态当期 feed（双月刊），改用 CrossRef，见下方
    ("American Sociological Review",         "https://journals.sagepub.com/action/showFeed?jc=asr&type=etoc&feed=rss"),
    ("Annual Review of Sociology",           "https://www.annualreviews.org/action/showFeed?type=etoc&feed=rss&jc=soc"),
    # SMR: Sage RSS 已失效（最新条目 2025-04），改用 CrossRef，见下方
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
    # OUP 期刊（QJE、RES、RFS）改用 CrossRef，见下方
    ("Journal of Political Economy",         "https://www.journals.uchicago.edu/action/showFeed?type=etoc&feed=rss&jc=jpe"),
    ("Econometrica",                         "https://onlinelibrary.wiley.com/feed/14680262/most-recent"),
    # 金融
    ("The Journal of Finance",               "https://onlinelibrary.wiley.com/feed/15406261/most-recent"),
    # 经济史
    ("The Journal of Economic History",      "https://www.cambridge.org/core/rss/product/id/677F550CB2C69EFA1656654D487DE504"),
]

CROSSREF_JOURNALS = [
    ("American Economic Review",                   "0002-8282"),
    ("The Review of Economics and Statistics",     "0034-6535"),
    ("American Economic Journal: Applied Economics","1945-7782"),
    ("American Economic Review: Insights",         "2640-205X"),
    # OUP RSS 为静态当期期号 feed，改用 CrossRef
    ("The Quarterly Journal of Economics",         "0033-5533"),
    ("The Review of Economic Studies",             "0034-6527"),
    ("Review of Financial Studies",                "0893-9454"),
    # AJS: Chicago etoc 为静态当期 feed（双月刊），改用 CrossRef
    ("American Journal of Sociology",              "0002-9602"),
    # SMR: Sage RSS 已失效，改用 CrossRef
    ("Sociological Methods & Research",            "0049-1241"),
]


# ── PNAS 特有处理 ──────────────────────────────────────────────────────────────

def _clean_pnas_authors(text: str) -> str:
    """清洗 PNAS RSS 中作者与机构粘连字段，仅保留作者部分。"""
    if not text:
        return ""
    cleaned = re.sub(r"\s+", " ", text).strip()
    cleaned = re.sub(r"^By\s+", "", cleaned, flags=re.IGNORECASE)
    for pat in (
        r"\bAuthor affiliations?\b.*$",
        r"\bAffiliations?\b.*$",
        r"\bContributed by\b.*$",
        r"\bEdited by\b.*$",
        r"\bCompeting interest\b.*$",
    ):
        cleaned = re.sub(pat, "", cleaned, flags=re.IGNORECASE).strip()
    m = re.search(
        r"(?i)(?:^|[;|.,])\s*(Department of|School of|College of|"
        r"University of|Institute of|Hospital|Center for|Laboratory|Academy of)\b",
        cleaned,
    )
    if m and m.start() > 0:
        cleaned = cleaned[:m.start()].rstrip(" ,;|.")
    return cleaned


def _pnas_abstract_filter(text: str) -> bool:
    """PNAS 卷期元数据不是真实摘要，返回 False 触发摘要补充。"""
    if re.match(r"^Proceedings of the National Academy of Sciences,\s+Volume\s+\d+,\s+Issue\s+\d+", text):
        return False
    return True


def _huang_entry_transform(entry, item: dict) -> dict | None:
    """PNAS 作者字段清洗，其余条目原样通过。"""
    if item.get("link", "") and "pnas.org" in item["link"]:
        item["authors"] = _clean_pnas_authors(item["authors"])
    return item


CONFIG = tracker_core.TrackerConfig(
    script_name="huang",
    start_date=date(2026, 3, 30),
    env_recipient="EMAIL_RECIPIENT_HUANG",
    journals=JOURNALS,
    crossref_journals=CROSSREF_JOURNALS,
    extra_abstract_filter=_pnas_abstract_filter,
    per_entry_transform=_huang_entry_transform,
)


def main(shared_top5_articles=None, shared_top5_article_errors=None, shared_top5_issues=None):
    tracker_core.run_tracker(
        CONFIG, shared_top5_articles, shared_top5_article_errors, shared_top5_issues
    )


if __name__ == "__main__":
    main()
