# CLAUDE.md — Journal Tracker 项目规范

## 项目结构

```
journal-tracker/
├── journal_tracker.py       # 主追踪器（19 个期刊）
├── yifanxu.py               # 子追踪器（8 个经济学核心期刊）
├── seen_articles.json        # 主追踪器已发送缓存
├── seen_yifanxu.json         # 子追踪器已发送缓存（首次运行后自动生成）
├── requirements.txt
├── NOTES.md                  # 本地进度文档（不同步 GitHub）
├── .github/workflows/
│   └── weekly_digest.yml     # GitHub Actions 定时任务
└── CLAUDE.md                 # 本文件
```

## 工作流规范

### 每次修改后必须执行

1. **记录进度**：将本次改动摘要追加到 `NOTES.md` 的「进度日志」章节（日期 + 改动要点）
2. **推送 GitHub**：所有代码改动（`.py`、`.yml`、`README.md`）必须提交并推送至 GitHub main 分支；`NOTES.md` 不推送（已加入 `.gitignore`）

### 提交规范

使用语义化 commit message：
- `feat:` 新功能
- `fix:` 修复问题
- `refactor:` 重构（不改变行为）
- `ci:` workflow / Actions 相关
- `docs:` 仅文档改动

### 测试流程

- 新功能/脚本：先用 `--test` 模式（不写缓存）验证邮件收发正常
- 通过后再合并进正式运行流程
- 测试用的临时 workflow 在测试完成后立即删除

## 脚本规范

- 两个脚本（`journal_tracker.py` / `yifanxu.py`）**独立维护，不共享代码**，保持各自完整可运行
- 新增期刊：同时考虑是否需要加入两个脚本
- 环境变量统一从 `os.environ` 读取，不硬编码敏感信息
- 缓存文件名与脚本对应，不交叉引用

## GitHub Secrets 一览

| Secret | 用途 | 脚本 |
|--------|------|------|
| `EMAIL_SENDER` | 发件邮箱 | 两个脚本共用 |
| `EMAIL_PASSWORD` | SMTP 授权码 | 两个脚本共用 |
| `EMAIL_RECIPIENT` | 主追踪器收件地址 | `journal_tracker.py` |
| `EMAIL_RECIPIENT_YIFAN` | 子追踪器收件地址 | `yifanxu.py` |

新增脚本时，若需独立收件人，在 GitHub repo Settings → Secrets 中添加对应条目，并在 `weekly_digest.yml` 的 `env:` 块中传入。

## 数据源优先级

1. **RSS**（优先）：实时性好，直接从出版社拉取
2. **CrossRef API**（备选）：用于无公开 RSS 的期刊（如 AER），抓取近 90 天内发表文章

新增期刊时，先查出版社网站是否提供 RSS；无 RSS 则用 CrossRef（需要 ISSN）。
