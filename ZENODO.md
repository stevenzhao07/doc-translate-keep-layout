# Zenodo DOI · 还差一步，需要你登录

## 现状

仓库已公开、`v0.5.0` Release 已发布：

- 仓库：https://github.com/stevenzhao07/doc-translate-keep-layout
- Release：https://github.com/stevenzhao07/doc-translate-keep-layout/releases/tag/v0.5.0

**DOI 我做不了** —— Zenodo 要么走 OAuth 授权 GitHub 仓库，要么用 API token，两者都需要你的账号登录。这不是权限配置问题，是身份问题。

## 两条路，选一条

### 路 A：开一次 GitHub 集成（推荐，一次配置永久生效）

1. 登录 https://zenodo.org ，用 GitHub 账号登录最省事
2. 进 https://zenodo.org/account/settings/github/
3. 在仓库列表里找到 `stevenzhao07/doc-translate-keep-layout`，把开关拨到 **ON**
4. 回 GitHub，在 Release 页面点 **Edit → Update release**（或新建一个 `v0.5.1`）

Zenodo 会立刻归档并生成 DOI，形如 `10.5281/zenodo.XXXXXXX`，同时自动挂一个 concept DOI（永远指向最新版）。

**好处**：以后每次发 Release 都自动拿 DOI，不用再管。

### 路 B：手动上传（不想授权也行）

1. https://zenodo.org/uploads/new
2. 上传 GitHub Release 里的 Source code (zip)
3. Type 选 **Software**，填标题/作者/许可证
4. Publish → 拿 DOI

缺点：每次发版要手动做一次，且和 GitHub 版本不联动。

## 元数据已经备好了

仓库里放了 `CITATION.cff`，Zenodo 会直接读它：

| 字段 | 值 |
|---|---|
| 标题 | doc-translate-keep-layout: document translation that keeps layout, with a fail-closed pre-flight gate |
| 作者 | Xinghua Zhao（ORCID `0009-0001-0512-1237`） |
| 版本 | 0.5.0 |
| 许可 | MIT |
| 关键词 | document translation / docx / pptx / layout preservation / terminology consistency / audit trail / medical device documentation |

**注意**：`CITATION.cff` 里用的是个人署名 + ORCID，没有挂公司名。这跟 W3C 那边"个人参与者"的口径一致，也避免把商业主体写进可被引用的学术记录里。

## 拿到 DOI 之后做什么

1. 把 DOI 徽章加进 README 顶部（`[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.XXXXXXX.svg)](https://doi.org/10.5281/zenodo.XXXXXXX)`）
2. 在 FG-TIDA / W3C 的发言里就可以写"见 DOI 10.5281/zenodo.XXXXXXX" —— **这是唯一能被外部引用、且不依赖任何人信任你的凭证**
3. 项目页 `stevenzhao07/stevenzhao07` 里加一行链接
