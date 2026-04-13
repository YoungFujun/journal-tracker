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

1. **RSS**（优先）：实时性好，直接从出版社拉取；保留 **21 天**内发表的文章
2. **CrossRef API**（备选/OUP 专用）：用于无 RSS 期刊及 OUP 期刊（QJE/RES/RFS），抓取近 21 天内发表文章
3. **OpenAlex API**（摘要补充）：对 RSS/CrossRef 未提供摘要的文章，通过 DOI 精确查询补充；不做标题搜索（会导致错误匹配）

**ScienceDirect 特殊处理**：RSS 链接为 PII 格式（无 DOI），且 RSS 的 `summary` 字段为卷期元数据而非摘要；作者和发布月份从 `summary` 中正则提取，摘要跳过补充直接留空。

**静态当期 RSS（不可用）**：以下出版商的 RSS 以整期为单位更新，期间内所有文章日期固定在上一期出版日，可能超过窗口很久：
- **OUP**（QJE/RES/RFS）：季刊，文章发布日距今常超 90 天 → 改用 CrossRef
- **Chicago etoc 双月刊以上**（AJS）：文章日期固定在出版日，advance access 文章不出现在 RSS → 改用 CrossRef
- 识别方法：检查 RSS 所有条目是否日期完全相同，或最新条目日期远早于今天

**Chicago etoc RSS 滞后（仍可用）**：JPE/JOLE 的 RSS published 日期（正式出版日）早于文章实际进入 feed 的日期（约晚 1 周），21 天窗口可覆盖此延迟。

**RSS 静默失效**：Sage 等平台的 RSS 可能在无告警的情况下停止更新（fail_count 不会增加，因为 fetch 不报错，只是返回旧文章）。目前 SMR（Sociological Methods & Research）已出现此情况 → 改用 CrossRef。

新增期刊时的决策顺序：
1. 检查出版商：OUP / Chicago 双月刊以上 → 直接用 CrossRef（不试 RSS）
2. 用 CrossRef 核查近 21 天有无文章（见下方核查脚本），确认 ISSN 正确
3. 若用 RSS：观察首次运行后 feed 条目的日期分布，全部相同日期 = 静态 feed，需迁移 CrossRef

## 本地开发注意事项

缓存文件（`seen_*.json`、`fail_counts_*.json`）必须保留在远端仓库供 GitHub Actions 使用，但本地无需同步。已对这些文件执行：

```bash
git update-index --skip-worktree seen_articles.json seen_yifanxu.json seen_haihuang.json seen_jiahuitan.json fail_counts_journal_tracker.json fail_counts_yifanxu.json fail_counts_haihuang.json fail_counts_jiahuitan.json
```

新克隆仓库后需重新执行上述命令，否则这些文件会出现在 `git status` 中。

## 缓存状态管理

**重要**：本地 `seen_*.json` 因 `skip-worktree` 不跟踪 GitHub Actions 的写入，本地文件是陈旧的。调试时始终查远端：

```bash
# 查看远端缓存（不影响本地文件）
git fetch origin
git show origin/main:seen_articles.json | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d),'entries')"

# 检查某个 DOI 是否已发送
git show origin/main:seen_articles.json | python3 -c "
import json,sys,urllib.parse
seen = set(json.load(sys.stdin))
doi = '10.1086/739323'  # 替换为要查的 DOI
url = f'https://www.journals.uchicago.edu/doi/abs/{doi}?af=R'
print('in seen:', doi in seen or url in seen)
"
```

**核查某期刊是否有漏文**（以 CrossRef 为准）：

```bash
python3 -c "
import urllib.request, json, subprocess
from datetime import datetime, timezone, timedelta

issn = '0022-3808'  # JPE；替换为目标期刊 ISSN
from_date = (datetime.now(timezone.utc) - timedelta(days=21)).strftime('%Y-%m-%d')
url = f'https://api.crossref.org/journals/{issn}/works?sort=published&order=desc&rows=30&filter=from-pub-date:{from_date}&select=DOI,title,published'
req = urllib.request.Request(url, headers={'User-Agent': 'journal-tracker/1.0'})
items = json.loads(urllib.request.urlopen(req, timeout=15).read())['message']['items']

seen = set()
for fname in ['seen_articles.json','seen_yifanxu.json','seen_haihuang.json','seen_jiahuitan.json']:
    r = subprocess.run(['git','show',f'origin/main:{fname}'], capture_output=True, text=True)
    if r.returncode == 0: seen |= set(json.loads(r.stdout))

for item in items:
    doi = item.get('DOI','')
    title = ' '.join(item.get('title',['?']))
    pd = item.get('published',{}).get('date-parts',[[]])[0]
    pub = '-'.join(str(p) for p in pd) if pd else '?'
    url_var = f'https://www.journals.uchicago.edu/doi/abs/{doi}?af=R'
    sent = doi in seen or url_var in seen
    print(f'[{pub}] {\"✓\" if sent else \"✗\"} {title[:65]}')
"
```
