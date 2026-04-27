import os

import top5_tracker


def _env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def main():
    print("=== Shared Top 5 fetch ===")
    shared_top5_articles, shared_top5_article_errors = top5_tracker.fetch_top5_recent_articles()
    shared_top5_issues, shared_top5_issue_errors = top5_tracker.fetch_top5_latest_issues()
    print(
        f"Top 5 recent article journals: {len(shared_top5_articles)}; "
        f"Top 5 issue journals: {len(shared_top5_issues)}"
    )
    if shared_top5_article_errors:
        print(f"Top 5 article fetch errors: {shared_top5_article_errors}")
    if shared_top5_issue_errors:
        print(f"Top 5 issue fetch errors: {shared_top5_issue_errors}")

    runners = [
        ("RUN_MAIN", True, "journal_tracker"),
        ("RUN_YIFANXU", True, "yifanxu"),
        ("RUN_HAIHUANG", True, "haihuang"),
        ("RUN_JIAHUITAN", True, "jiahuitan"),
        ("RUN_SHANGYIN", True, "shangyin"),
    ]

    for env_name, default_enabled, module_name in runners:
        if not _env_flag(env_name, default_enabled):
            print(f"Skip {module_name}")
            continue
        print(f"=== Run {module_name} ===")
        module = __import__(module_name)
        module.main(
            shared_top5_articles=shared_top5_articles,
            shared_top5_article_errors=shared_top5_article_errors,
            shared_top5_issues=shared_top5_issues,
        )


if __name__ == "__main__":
    main()
