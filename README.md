# Journal RSS Tracker

每周自动追踪经济学、金融学、经济史等领域期刊的最新文章，通过邮件发送摘要。
完全运行在 GitHub Actions 上，**免费、无需服务器、无需本地运行**。

---

## 功能

- 覆盖 16 个主流期刊（见下表），每周一北京时间 09:00 自动运行
- 仅推送过去 **21 天**内发表、且上次运行后新出现的文章，不重复、不遗漏（21 天窗口可覆盖部分出版商 RSS 的时间戳滞后问题）
- 邮件标题包含期号（第1期、第2期……），自动按发送日期递增计算
- 邮件包含：文章标题（可点击跳转）、作者、发布日期、摘要（通过 OpenAlex API 补充；ScienceDirect 期刊 RSS 不提供摘要，仅显示标题与作者）
- 邮件内每个期刊分两组展示：有摘要文章排前（摘要置于灰色框内），无摘要文章排后并附提示
- 支持多收件人
- 内置 RSS 失效检测：某期刊连续 5 周抓取失败，自动发送告警邮件（含错误信息）

**已收录期刊**

| 领域 | 期刊 |
|------|------|
| 综合经济学 | The Quarterly Journal of Economics · Journal of Political Economy · The Review of Economic Studies · Econometrica · American Economic Review |
| 劳动/发展/公共 | Journal of Labor Economics · Journal of Development Economics · Journal of Public Economics · The Economic Journal · Journal of Population Economics · The Review of Economics and Statistics |
| 中国经济 | China Economic Review |
| 金融 | Journal of Financial Economics · The Journal of Finance · Review of Financial Studies |
| 经济史 | The Journal of Economic History |

---

## 脚本说明

| 文件 | 说明 | 期刊数 |
|------|------|--------|
| `run_all_trackers.py` | **统一入口**，每周正式运行时先抓一次五大刊公共内容，再依次调度主程序和各可选预设 | - |
| `top5_tracker.py` | **公共模块**，负责五大刊（AER、QJE、JPE、Econometrica、REStud）的近期新文章抓取与最新一期目录抓取 | 5 |
| `tracker_core.py` | **核心执行器**，包含所有公共逻辑（抓取、摘要补充、HTML 渲染、发信、状态持久化）；各预设脚本通过配置调用，不重复维护 | - |
| `journal_tracker.py` | **主程序**，覆盖经济/金融/经济史等领域期刊，并消费公共五大刊内容 | 16 |
| `xu.py` | 可选预设，聚焦较窄的核心经济学期刊，并消费公共五大刊内容 | 8 |
| `huang.py` | 可选预设，覆盖更宽的经济/社会/政治/金融/经济史来源，并消费公共五大刊内容 | 26 |
| `tan.py` | 可选预设，覆盖经济/公共/卫生经济学等领域期刊，并消费公共五大刊内容 | 15 |
| `yin.py` | 可选预设，聚焦经济学 Top 5、城市经济与区域经济工作论文，并消费公共五大刊内容 | 7 |

各脚本独立维护缓存文件，互不干扰。缓存和失败计数文件统一放在 `state/` 目录，由 GitHub Actions 自动更新。附加预设只是示例，Fork 后可按需删除、修改或新增。

日常周报由 `run_all_trackers.py` 统一调度。五大刊的近期新文章抓取和最新一期目录抓取会在每次运行时先统一执行一次，再分别对照各脚本自己的缓存文件判断”是否已推送”。这样既保留了各脚本独立的收件人、缓存和发信逻辑，也避免对五大刊重复请求。各单独脚本仍可直接运行，适合本地调试或后续扩展。

**新增预设**：复制任意一个预设文件，修改顶部的 `JOURNALS`、`CROSSREF_JOURNALS` 和 `CONFIG` 字段，再接入 `run_all_trackers.py` 和 `weekly_digest.yml` 的输入开关即可，无需了解核心执行逻辑。

---

## 更新记录

- **2026-05-04**：重构内部结构，将所有公共逻辑抽取到 `tracker_core.py`，各预设脚本改为薄包装（只保留期刊列表和配置），新增 `--preview` 本地预览模式（全量抓取，生成 HTML，不发信）。修正 Top 5 最新一期目录识别：AER、QJE、REStud 改为官网当前期页面优先、CrossRef 回退。
- **2026-04-27**：新增最新一期目录追加功能（五大刊发布新一期时，在邮件末尾附上完整目录，注明哪些文章曾在此前邮件中出现）；新增 Semantic Scholar API 作为摘要补充备选源（OpenAlex 未覆盖时自动回退）；邮件抬头新增"X 本期刊发布了最新一期目录"提示；后续又将五大刊的新文章与目录抓取抽为公共步骤，每次运行只抓一次，再分别对照各脚本缓存。
- **2026-04-20**：重做邮件正文版式（白底目录风格，去掉横幅和摘要框背景，期刊分区标题加粗线，文章条目去掉序号和分割线）；修正 HTML 标签裸露问题；去掉顶部抬头区的浅色分割线。
- **2026-04-20**：修正 PNAS RSS 卷期元数据误判为摘要的问题。
- **2026-04-20**：将缓存和失败计数 JSON 移入 `state/`，减少根目录文件数量。
- **2026-04-13**：抓取窗口扩展为 21 天；OUP、AJS、SMR 等静态或失效 RSS 迁到 CrossRef；修复 Wiley 链接去重问题。
- **2026-04-07**：摘要补充改为 OpenAlex DOI 精确查询；邮件按有摘要/无摘要分组展示；补充 ScienceDirect 特殊处理。
- **2026-03-30**：新增附加预设、手动运行开关、期号标题、RSS 失败告警和缓存自动提交。

完整维护记录见 [CHANGELOG.md](CHANGELOG.md)。

---

## 快速开始（Fork 后 5 分钟完成部署）

### 第一步：Fork 本仓库

点击右上角 **Fork**，将仓库复制到你的 GitHub 账户下。

### 第二步：准备 163 邮箱 SMTP 授权码

1. 登录 [mail.163.com](https://mail.163.com)
2. 进入 **设置 → POP3/SMTP/IMAP**
3. 开启「IMAP/SMTP 服务」，按提示发短信验证
4. 获得 **16 位授权码**（不是登录密码，妥善保存）

### 第三步：配置 GitHub Secrets

进入你的 Fork 仓库 → **Settings → Secrets and variables → Actions → New repository secret**，添加以下 Secret（附加预设 Secret 按需添加）：

| Secret 名称 | 填写内容 | 必填 |
|---|---|---|
| `EMAIL_SENDER` | 163 邮箱地址，如 `yourname@163.com` | 是 |
| `EMAIL_PASSWORD` | 第二步获得的 SMTP 授权码 | 是 |
| `EMAIL_RECIPIENT` | 主程序收件地址，多地址用英文逗号分隔 | 是 |
| `EMAIL_RECIPIENT_XU` | xu 预设收件地址 | 使用该预设时 |
| `EMAIL_RECIPIENT_HUANG` | huang 预设收件地址 | 使用该预设时 |
| `EMAIL_RECIPIENT_TAN` | tan 预设收件地址 | 使用该预设时 |
| `EMAIL_RECIPIENT_YIN` | yin 预设收件地址（例如 `friendname@example.com`） | 使用该预设时 |
| `EMAIL_ALERT` | RSS 失效告警收件地址 | 启用告警功能时 |

### 第四步：手动触发一次测试

进入仓库 → **Actions → Weekly Journal Digest → Run workflow**

弹出面板中可勾选要运行的脚本。**首次建议只勾选主程序（`run_main`），其余预设取消勾选**，点击 **Run workflow** 触发。约 30 秒后检查邮箱（注意垃圾邮件文件夹）。收到邮件即主程序部署成功。

> **注意：** 每个预设脚本都必须在 Secrets 中配置对应的收件人变量（如 `EMAIL_RECIPIENT_XU`），否则运行时会因读不到环境变量而报错。未配置 Secret 的预设，触发时务必取消对应的勾选。

> 手动触发时可只勾选某个脚本单独运行，方便调试或补发。

---

## 自定义期刊列表

打开 `journal_tracker.py`，找到 `JOURNALS` 列表：

```python
JOURNALS = [
    ("期刊名称", "RSS feed URL"),
    ...
]
```

- **删除**：直接删除对应行
- **新增**：添加一行 `("期刊名", "RSS URL")`

大多数期刊可在出版社网站找到 RSS 链接：
- **Elsevier (ScienceDirect)**：`https://rss.sciencedirect.com/publication/science/{ISSN（去掉连字符）}`
- **Wiley**：`https://onlinelibrary.wiley.com/feed/{eISSN（去掉连字符）}/most-recent`
- **Oxford (OUP)**：OUP RSS 为静态当期 feed，**建议直接用 CrossRef**，不用 RSS

对于没有公开 RSS、或 RSS 存在以下问题的期刊，本项目使用 [CrossRef API](https://api.crossref.org) 作为数据来源：

- **无 RSS**（如 AER）
- **OUP 期刊**（QJE、RES、RFS 等）：OUP RSS 是静态当期 feed，季刊/双月刊的间隔期内文章日期不更新，任何时间窗口都无法覆盖
- **Chicago etoc 双月刊以上**（如 AJS）：同类静态 feed 问题，且 advance access 文章不出现在 RSS
- **RSS 已失效**（如 SMR，Sage 平台某些期刊停止更新 RSS）

在 `CROSSREF_JOURNALS` 列表中填写期刊名和 ISSN 即可：

```python
CROSSREF_JOURNALS = [
    ("期刊名称", "ISSN（带连字符）"),
    ...
]
```

新增期刊时，建议先用 CrossRef API 确认 ISSN 正确（能查到近期文章）。不确定应用 RSS 还是 CrossRef 时，优先选 CrossRef（数据更可靠，不受 feed 格式影响）。

**本地预览（不发信）：** 修改期刊列表后，可在本地用 `--preview` 模式验证效果：

```bash
python journal_tracker.py --preview
```

这会执行完整抓取流程，将邮件正文渲染为 `preview_journal_tracker.html`，在浏览器中打开即可预览。不发送邮件，不更新缓存。附加预设同理（如 `python yin.py --preview`）。

---

## 修改运行时间

默认每周一 UTC 01:00（北京/东京时间 09:00）自动运行。
如需修改，编辑 `.github/workflows/weekly_digest.yml` 中的 cron 表达式：

```yaml
- cron: "0 1 * * 1"   # 分 时 日 月 周（1=周一）
```

---

## RSS 失效检测与告警

每个脚本独立维护一份失败计数文件（`fail_counts_*.json`），记录各期刊的连续抓取失败次数：

- 抓取**成功**：该期刊计数归零
- 抓取**失败**：计数 +1
- 计数恰好达到 **5**（即连续失败满 5 周）：自动向告警地址发送邮件

告警邮件包含：失败期刊名称、连续失败周数、具体错误信息，方便判断是偶发网络问题还是 RSS 地址已失效。

**配置方法：** 在 GitHub Secrets 中添加 `EMAIL_ALERT`，填写你的邮箱地址（见上方 Secret 表格）。不配置则静默跳过，不影响正常推送。

**收到告警后的处理步骤：**

1. 进入仓库 → **Actions** → 找到最近一次运行，查看对应脚本的日志
2. 确认该期刊显示 `ERROR` 及错误原因
3. 前往出版社官网获取新的 RSS 地址（参考下方「自定义期刊列表」中各出版商 RSS 格式）
4. 编辑对应脚本，更新 URL，提交即可；下次运行成功后计数自动归零

---

## 工作原理

1. GitHub Actions 按计划触发 `run_all_trackers.py`
2. 统一抓取一次五大刊（AER、QJE、JPE、Econometrica、REStud）的近期新文章和最新一期目录；其中 AER、QJE、REStud 的目录判断优先参考官网当前期页面，CrossRef 作为回退
3. 主程序和各附加预设分别抓取自己的非五大刊来源
4. 各脚本将公共五大刊内容与自己的缓存文件对照，筛出本周新增文章，并判断最新一期目录中哪些文章此前已经推送过
5. 通过 OpenAlex API（DOI 精确查询）为缺少摘要的文章补充摘要；OpenAlex 未覆盖时回退至 Semantic Scholar API；ScienceDirect 期刊跳过（RSS 无公开 DOI）
6. 若检测到五大刊有新一期目录，则在邮件末尾追加完整目录，并注明哪些文章曾在此前邮件中出现
7. 将新文章整理成 HTML 邮件（有摘要/无摘要分组展示），通过 163 SMTP 发送
8. 更新缓存并提交回仓库，确保下次运行不重复

---

## 常见问题

**Q：收不到邮件？**
先检查垃圾邮件文件夹；再确认 163 SMTP 授权码正确（不是登录密码）；163 SMTP 服务有时会因长期未使用而自动关闭，需重新开启。

**Q：某个期刊一直没有更新？**
在 Actions 日志中查看该期刊是否显示 `ERROR`。若是，表明 RSS 地址已失效，需更新 URL。配置 `EMAIL_ALERT` Secret 后，连续失败 5 周会自动收到告警邮件，无需手动检查。

**Q：如何只保留自己关注的期刊？**
直接编辑 `journal_tracker.py`，删除不需要的行后提交即可。

**Q：如何添加自己的附加预设？**
复制任意一个预设文件，修改顶部的 `JOURNALS`、`CROSSREF_JOURNALS` 和 `CONFIG`（`script_name`、`env_recipient`、`start_date`），再把新脚本接入 `run_all_trackers.py` 和 `weekly_digest.yml` 的输入开关即可。所有抓取和发信逻辑由 `tracker_core.py` 自动处理，不需要改动。
