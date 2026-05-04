"""
xu — 可选期刊预设
覆盖经济学核心 8 个期刊。

用法：
  正常运行（增量，更新缓存）:  python xu.py
  测试运行（全量，不写缓存）:  python xu.py --test
  本地预览（生成HTML，不发信）: python xu.py --preview
"""

from datetime import date
import tracker_core

JOURNALS = [
    # OUP 期刊（QJE、RES）改用 CrossRef，见下方
    ("Journal of Political Economy",       "https://www.journals.uchicago.edu/action/showFeed?type=etoc&feed=rss&jc=jpe"),
    ("Econometrica",                       "https://onlinelibrary.wiley.com/feed/14680262/most-recent"),
    ("Journal of Labor Economics",         "https://www.journals.uchicago.edu/action/showFeed?type=etoc&feed=rss&jc=jole"),
    ("Journal of Development Economics",   "https://rss.sciencedirect.com/publication/science/03043878"),
    ("Journal of Human Resources",         "https://jhr.uwpress.org/rss/recent.xml"),
]

# OUP RSS 为静态当期期号 feed，改用 CrossRef
CROSSREF_JOURNALS = [
    ("American Economic Review",           "0002-8282"),
    ("The Quarterly Journal of Economics", "0033-5533"),
    ("The Review of Economic Studies",     "0034-6527"),
]

CONFIG = tracker_core.TrackerConfig(
    script_name="xu",
    start_date=date(2026, 3, 30),
    env_recipient="EMAIL_RECIPIENT_XU",
    journals=JOURNALS,
    crossref_journals=CROSSREF_JOURNALS,
)


def main(shared_top5_articles=None, shared_top5_article_errors=None, shared_top5_issues=None):
    tracker_core.run_tracker(
        CONFIG, shared_top5_articles, shared_top5_article_errors, shared_top5_issues
    )


if __name__ == "__main__":
    main()
