# Changelog

本文件记录项目的主要维护变更。日常缓存更新（`seen_*.json`、`fail_counts_*.json`）不单独列入。

## 2026-04-20

### 修正 PNAS RSS 元数据误判

- `haihuang.py` 新增 PNAS 卷期元数据识别规则。
- 以 `Proceedings of the National Academy of Sciences, Volume ..., Issue ...` 开头的 RSS summary 不再作为真实摘要展示。
- 这类文章会优先通过 OpenAlex DOI 精确查询补摘要；若补不到，则归入无摘要组。

## 2026-04-13

### 扩大抓取窗口并修正数据源

- 抓取窗口从 7 天扩展为 21 天，降低出版商 RSS 时间戳滞后导致漏文的风险。
- 将 OUP 期刊（QJE、RES、RFS）迁到 CrossRef，避开静态当期 RSS 的日期问题。
- 将 AJS、SMR 等不适合继续依赖 RSS 的期刊迁到 CrossRef。
- 修复 Wiley 链接中的 `?af=R` 变体，减少同一文章因链接形式不同而重复发送。

### 一次性补跑与清理

- 新增一次性 catch-up 脚本和 workflow，用于补齐窗口调整后的缓存。
- 补跑完成后删除临时脚本和 workflow，保留常规每周运行流程。

## 2026-04-07

### 摘要补充逻辑重写

- 摘要补充从 CrossRef 改为 OpenAlex API。
- 仅使用 DOI 精确查询，不再使用标题搜索兜底，避免错误匹配到无关文章摘要。
- 新增 `_is_real_abstract()`，过滤 RSS 中常见的元数据占位文本。
- ScienceDirect 期刊因 RSS 无公开 DOI，跳过 OpenAlex 摘要补充，直接按无摘要文章展示。
- 对 ScienceDirect RSS 的作者和日期做特殊解析，从 summary 元数据中提取 `Author(s):` 和 `Publication date:`。

### 邮件布局重构

- 每个期刊内按摘要状态分组：有摘要文章排前，无摘要文章排后。
- 有摘要文章使用灰色摘要框展示。
- 无摘要文章前显示统一提示，引导读者点击标题查看全文。
- 调整期刊标题栏样式，提高邮件可读性。

## 2026-03-30

### 子追踪器和手动运行

- 新增 `yifanxu.py`、`haihuang.py`、`jiahuitan.py` 三个个性化子追踪器。
- GitHub Actions 支持手动触发时选择运行某个脚本，便于测试和补发。
- 各脚本独立维护收件人、缓存文件和失败计数文件。

### 期刊范围调整

- 主程序 `journal_tracker.py` 从 19 个期刊调整为 16 个期刊。
- `jiahuitan.py` 修正为经济、公共和卫生经济学方向。
- `haihuang.py` 保留更宽的经济、社会、政治、金融和经济史覆盖范围。

### 邮件标题和缓存管理

- 邮件标题加入自动递增期号，如 `第N期 · Journal Weekly Digest`。
- 远端缓存文件由 GitHub Actions 自动提交维护。
- 本地缓存文件设置为 `skip-worktree`，避免本地陈旧缓存干扰开发。

### RSS 失效告警

- 四个脚本加入 RSS/CrossRef 连续失败计数。
- 某期刊连续失败达到 5 次时，向 `EMAIL_ALERT` 发送告警邮件。

## 2026-03-29

### 项目初始化

- 建立主追踪器 `journal_tracker.py`。
- 部署 GitHub Actions，每周一北京时间 09:00 自动运行。
- 通过 163 SMTP 发送期刊更新邮件。
