# CLAUDE.md — Journal Tracker 项目规范

## 项目结构

```
journal-tracker/
├── journal_tracker.py        # 【主程序】覆盖经济/金融/经济史 16 个期刊
├── yifanxu.py                # 【个性化子程序】为朋友定制，经济学核心 8 个期刊
├── haihuang.py               # 【个性化子程序】为朋友定制，经济/社会/政治/金融/史 26 个期刊
├── jiahuitan.py              # 【个性化子程序】为朋友定制，经济/公共/卫生经济学 15 个期刊
├── seen_articles.json              # 主程序缓存
├── seen_yifanxu.json               # yifanxu 缓存（首次运行后自动生成）
├── seen_haihuang.json              # haihuang 缓存（首次运行后自动生成）
├── seen_jiahuitan.json             # jiahuitan 缓存（首次运行后自动生成）
├── fail_counts_journal_tracker.json # 主程序 RSS 失败计数（自动生成）
├── fail_counts_yifanxu.json        # yifanxu RSS 失败计数（自动生成）
├── fail_counts_haihuang.json       # haihuang RSS 失败计数（自动生成）
├── fail_counts_jiahuitan.json      # jiahuitan RSS 失败计数（自动生成）
├── requirements.txt
├── NOTES.md                   # 本地进度文档（不同步 GitHub）
├── .github/workflows/
│   └── weekly_digest.yml      # GitHub Actions 定时任务（四个脚本顺序运行；手动触发时可按需选择）
└── CLAUDE.md                  # 本文件
```

## 工作流规范

### 每次修改后必须执行

1. **同步文字描述**：凡涉及期刊数量、领域、功能的改动，须同步更新以下位置的对应描述：
   - 本文件（`CLAUDE.md`）的项目结构注释
   - `README.md` 的功能介绍、已收录期刊表、脚本说明表
2. **记录进度**：将本次改动摘要追加到 `NOTES.md` 的「进度日志」章节（日期 + 改动要点）
3. **推送 GitHub**：所有代码改动（`.py`、`.yml`、`README.md`、`CLAUDE.md`）必须提交并推送至 GitHub main 分支；`NOTES.md` 不推送（已加入 `.gitignore`）

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

- 四个脚本**独立维护，不共享代码**，保持各自完整可运行
- 主程序（`journal_tracker.py`）覆盖核心期刊；子程序为朋友个性化定制，期刊范围可与主程序重叠
- 邮件标题格式：`第N期 · Journal Weekly Digest · {total} new articles — {week_str}`；测试模式：`测试 · 第N期 · Journal Weekly Digest · ...`；期号由 `START_DATE = date(2026, 3, 30)` 与当前日期计算得出
- 环境变量统一从 `os.environ` 读取，不硬编码敏感信息
- 缓存文件名与脚本对应（`seen_<scriptname>.json`、`fail_counts_<scriptname>.json`），不交叉引用
- 新增子程序时，参照现有子程序结构，并在 `weekly_digest.yml` 追加对应 step（含 `EMAIL_ALERT` 环境变量）
- RSS 失效检测：每个脚本独立维护 `fail_counts_*.json`，连续失败达 5 次时向 `EMAIL_ALERT` 发送告警；测试模式不触发告警、不更新计数

## GitHub Secrets 一览

| Secret | 用途 | 脚本 |
|--------|------|------|
| `EMAIL_SENDER` | 发件邮箱 | 所有脚本共用 |
| `EMAIL_PASSWORD` | SMTP 授权码 | 所有脚本共用 |
| `EMAIL_RECIPIENT` | 主程序收件地址 | `journal_tracker.py` |
| `EMAIL_RECIPIENT_YIFAN` | yifanxu 子程序收件地址 | `yifanxu.py` |
| `EMAIL_RECIPIENT_HAIHUANG` | haihuang 子程序收件地址 | `haihuang.py` |
| `EMAIL_RECIPIENT_JIAHUITAN` | jiahuitan 子程序收件地址 | `jiahuitan.py` |
| `EMAIL_ALERT` | RSS 失效告警收件地址（所有脚本共用） | 所有脚本 |

新增脚本时，若需独立收件人，在 GitHub repo Settings → Secrets 中添加对应条目，并在 `weekly_digest.yml` 的 `env:` 块中传入。

## 数据源优先级

1. **RSS**（优先）：实时性好，直接从出版社拉取；仅保留 7 天内发表的文章
2. **CrossRef API**（备选）：用于无公开 RSS 的期刊（如 AER），抓取近 7 天内发表文章
3. **OpenAlex API**（摘要补充）：对 RSS/CrossRef 未提供摘要的文章，通过 DOI 精确查询补充；不做标题搜索（会导致错误匹配）

**ScienceDirect 特殊处理**：RSS 链接为 PII 格式（无 DOI），且 RSS 的 `summary` 字段为卷期元数据而非摘要；作者和发布月份从 `summary` 中正则提取，摘要跳过补充直接留空。

新增期刊时，先查出版社网站是否提供 RSS；无 RSS 则用 CrossRef（需要 ISSN）。

## 本地开发注意事项

缓存文件（`seen_*.json`、`fail_counts_*.json`）必须保留在远端仓库供 GitHub Actions 使用，但本地无需同步。已对这些文件执行：

```bash
git update-index --skip-worktree seen_articles.json seen_yifanxu.json seen_haihuang.json seen_jiahuitan.json fail_counts_journal_tracker.json fail_counts_yifanxu.json fail_counts_haihuang.json fail_counts_jiahuitan.json
```

新克隆仓库后需重新执行上述命令，否则这些文件会出现在 `git status` 中。
