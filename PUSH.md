# 推送 GitHub · 被卡住的原因与两条出路

## 现状（2026-10-21 记）

试过了，**推不上去，原因是权限，不是缺内容**：

| 尝试 | 结果 |
|---|---|
| GitHub 连接器 `create_repository` | `403 Resource not accessible by integration` —— 当前令牌没有建仓权限（**试了两次，2026-10-21 10:35 仍 403**） |
| 已有仓 `user:stevenzhao07 doc-translate` | 0 个 —— 尚未建仓 |
| `gh` CLI | 本机 PATH 上没有 |
| `git` CLI | 同上，PowerShell 环境里既无 gh 也无 git |

包本身已经齐了（README / LICENSE / CI workflow / 14 条测试 / SKILL.md），**只差一个能写的手**。

## 出路 A：给连接器写权限（我这边就能全做完）

需要一个带 `repo` 权限的 fine-grained PAT，或把 GitHub 连接器重新授权为可写。有了之后我一条命令推完，并确认 Actions 跑绿。

## 出路 B：你本机两条命令

如果本机装了 GitHub Desktop / git，直接：

```bash
cd "D:\Workbuddy\2026-10-20-17-38-48\skills\doc-translate-keep-layout"
git init -b main
git add .
git commit -m "feat: doc-translate-keep-layout v0.3.0 — 保版式翻译 + fail-closed 闸门 + 审计哈希链"
```

先在 GitHub 网页建一个空仓（**不要**勾 README/.gitignore），然后：

```bash
git remote add origin https://github.com/stevenzhao07/doc-translate-keep-layout.git
git push -u origin main
```

## 推上去之后会自动发生什么

`.github/workflows/ci.yml` 会在 push 和 PR 时跑：

1. `python -m compileall` 语法检查
2. `python tests/run_tests.py` —— 14 条红队回归用例（Python 3.11 与 3.13 两个版本矩阵）
3. 合成样本全链路 map → apply → check
4. 把 `report.json` 摘要写进 job summary

这就是"我们的 clawsweeper"的第一层：**不靠人记得跑，靠 push 触发。**

## 建议

先建**私有仓**跑通 CI，绿了再转公开。公开那一刻才算"可达性"从 0 变成 1。
