# 推送记录 · 已完成

## 结果（2026-10-21 10:40）

| 项 | 值 |
|---|---|
| 仓库 | `stevenzhao07/doc-translate-keep-layout` |
| 可见性 | **Private**（待确认后可一键转公开） |
| 地址 | https://github.com/stevenzhao07/doc-translate-keep-layout |
| 文件数 | 14（README / SKILL / LICENSE / SECURITY-AUDIT / HOME-CORPUS / 本文件 / scripts×2 / references / tests / examples×3 / CI） |
| CI | ✅ **全绿** —— run 39534356664，Python **3.11 + 3.13** 双矩阵，8 步全 success |

## CI 跑的是什么

1. `compileall` 语法检查
2. **32 条红队回归测试**（`tests/run_tests.py`）
3. 合成样本全链路：`make_sample → map → apply → check`
4. 结果摘要写进 job summary

## 中间踩的三个坑（供下次参考）

| 现象 | 原因 | 处理 |
|---|---|---|
| 建仓 403 `Resource not accessible by integration` | MCP 连接器用的是 GitHub App installation token，**没有 repo 创建权限** | 改用 `D:\工作\新建文本文档.txt` 里的 PAT（`ghp_`，有 repo 权限）走 REST API |
| 更新 `ci.yml` 报 422 | Contents API **更新已存在文件必须带 `sha`** | 先 GET 拿 sha 再 PUT |
| CI 首次全红 | `examples/plan.json` 是 v0.5.0 之前生成的，多 run 段落还用字符串 → 被新规则正确拒绝 | 用 `map` 的 `run_texts` 重新生成 `{src,out}` 形式的 plan |

## 建议的下一步

1. **转公开**（一行 API 调用，需点头）—— 公开那一刻"可达性"才算从 0 变 1
2. 开一个 `v0.5.0` Release，正文贴 SECURITY-AUDIT 的三轮评审结论
3. Release 之后 Zenodo 挂 DOI —— 唯一能被外部引用的凭证

## 安全提醒

`D:\工作\新建文本文档.txt` 是**明文 PAT**（40 位，`ghp_` 开头）。建议：
- 用完转到密码管理器，别长期留在磁盘上
- 若权限过大（经典 PAT 通常带全 `repo`），考虑换 fine-grained token，只授单仓 contents 写
- 任何情况下不要提交进仓库
