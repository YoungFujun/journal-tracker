# Journal RSS Tracker

每周自动追踪经济学、金融学、卫生经济学期刊的最新文章，通过邮件发送摘要。
完全运行在 GitHub Actions 上，**免费、无需服务器、无需本地运行**。

---

## 功能

- 覆盖 19 个主流期刊（见下表），每周一北京时间 09:00 自动运行
- 仅推送上次运行后新出现的文章，不重复、不遗漏
- 邮件包含：文章标题（可点击跳转）、作者、发布日期、摘要
- 支持多收件人

**已收录期刊**

| 领域 | 期刊 |
|------|------|
| 综合经济学 | The Quarterly Journal of Economics · Journal of Political Economy · The Review of Economic Studies · Econometrica · American Economic Review |
| 劳动/发展/公共 | Journal of Labor Economics · Journal of Development Economics · Journal of Public Economics · The Economic Journal · The Review of Economics and Statistics |
| 中国经济 | China Economic Review |
| 金融 | Journal of Financial Economics · The Journal of Finance · Review of Financial Studies |
| 卫生/社会 | Journal of Health Economics · Health Economics · Social Science & Medicine |

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

进入你的 Fork 仓库 → **Settings → Secrets and variables → Actions → New repository secret**，添加三个 Secret：

| Secret 名称 | 填写内容 |
|---|---|
| `EMAIL_SENDER` | 163 邮箱地址，如 `yourname@163.com` |
| `EMAIL_PASSWORD` | 第二步获得的 SMTP 授权码 |
| `EMAIL_RECIPIENT` | 收件地址，多个地址用英文逗号分隔，如 `a@gmail.com,b@ruc.edu.cn` |

### 第四步：手动触发一次测试

进入仓库 → **Actions → Weekly Journal Digest → Run workflow → Run workflow**

约 30 秒后检查邮箱（注意垃圾邮件文件夹）。收到邮件即部署成功。

---

## 自定义期刊列表

打开 `fetch_and_notify.py`，找到 `JOURNALS` 列表：

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
- **Oxford (OUP)**：在期刊主页找 RSS 图标获取链接

对于没有公开 RSS 的期刊（如 AER、JEL），本项目使用 [CrossRef API](https://api.crossref.org) 作为数据来源，在 `CROSSREF_JOURNALS` 列表中填写期刊名和 ISSN 即可：

```python
CROSSREF_JOURNALS = [
    ("期刊名称", "ISSN（带连字符）"),
    ...
]
```

---

## 修改运行时间

默认每周一 UTC 01:00（北京/东京时间 09:00）自动运行。
如需修改，编辑 `.github/workflows/weekly_digest.yml` 中的 cron 表达式：

```yaml
- cron: "0 1 * * 1"   # 分 时 日 月 周（1=周一）
```

---

## 工作原理

1. GitHub Actions 按计划触发脚本
2. 脚本从各期刊 RSS/CrossRef 拉取文章列表
3. 与 `seen_articles.json`（存储已发送文章的 ID）对比，筛出新文章
4. 将新文章整理成 HTML 邮件，通过 163 SMTP 发送
5. 更新 `seen_articles.json` 并提交回仓库，确保下次运行不重复

---

## 常见问题

**Q：收不到邮件？**
先检查垃圾邮件文件夹；再确认 163 SMTP 授权码正确（不是登录密码）；163 SMTP 服务有时会因长期未使用而自动关闭，需重新开启。

**Q：某个期刊一直没有更新？**
在 Actions 日志中查看该期刊是否显示 `ERROR`。若是，表明 RSS 地址已失效，需更新 URL。

**Q：如何只保留自己关注的期刊？**
直接编辑 `fetch_and_notify.py`，删除不需要的行后提交即可。
