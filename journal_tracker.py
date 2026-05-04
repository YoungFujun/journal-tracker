"""
Journal RSS Tracker — 主程序
覆盖经济/金融/经济史 16 个期刊。

用法：
  正常运行（增量，更新缓存）:  python journal_tracker.py
  测试运行（全量，不写缓存）:  python journal_tracker.py --test
  本地预览（生成HTML，不发信）: python journal_tracker.py --preview
"""

from datetime import date
import tracker_core
import top5_tracker

JOURNALS = [
    # 综合经济学（OUP RSS 为当期期号静态 feed，改用 CrossRef，见下方）
    ("Journal of Political Economy",                   "https://www.journals.uchicago.edu/action/showFeed?type=etoc&feed=rss&jc=jpe"),
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
    # 经济史
    ("The Journal of Economic History",                "https://www.cambridge.org/core/rss/product/id/677F550CB2C69EFA1656654D487DE504"),
]

# OUP RSS 为静态当期期号 feed，季刊/双月刊期间内所有文章日期均超出窗口，改用 CrossRef
CROSSREF_JOURNALS = [
    ("American Economic Review",               "0002-8282"),
    ("The Review of Economics and Statistics", "0034-6535"),
    ("The Quarterly Journal of Economics",     "0033-5533"),
    ("The Review of Economic Studies",         "0034-6527"),
    ("Review of Financial Studies",            "0893-9454"),
]

CONFIG = tracker_core.TrackerConfig(
    script_name="journal_tracker",
    start_date=date(2026, 3, 30),
    env_recipient="EMAIL_RECIPIENT",
    journals=JOURNALS,
    crossref_journals=CROSSREF_JOURNALS,
)


def main(shared_top5_articles=None, shared_top5_article_errors=None, shared_top5_issues=None):
    tracker_core.run_tracker(
        CONFIG, shared_top5_articles, shared_top5_article_errors, shared_top5_issues
    )


if __name__ == "__main__":
    main()
