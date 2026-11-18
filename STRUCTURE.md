# STRUCTURE — 分层与改动代价

## 四层

| 层 | 文件 | 内容 |
|---|---|---|
| L1 引擎 | `scripts/translate_kit.py` | `.docx`/`.pptx` 解析、文本抽取、回填；纯标准库 |
| L2 术语 | `references/terminology.md`、`scripts/glossary_build.py` | 人工术语表与构建脚本 |
| L3 产物 | `examples/{plan.json,report.json,gate-report-demo.json}`、`examples/make_sample.py` | 计划、报告、门禁结果的结构与样例 |
| L4 检验 | `tests/run_tests.py`、`.github/workflows/ci.yml` | 端到端测试，CI 跑 |

## 改动代价

| 你想做 | 改哪里 | 必须重跑 | 必须同步 |
|---|---|---|---|
| 改文本抽取规则 | `translate_kit.py` | `tests/run_tests.py` | `examples/report.json` |
| 扩充术语 | `terminology.md` → 重新构建 | `glossary_build.py` | 术语数量说明 |
| 改报告结构 | `report.json` 生成逻辑 | 测试中的结构断言 | `gate-report-demo.json` |

## 边界

本仓只做**版式保真的文本替换与术语一致**，不做翻译质量判定。
译文的合规性归人；变更判定归 `lcas`；交付门禁归 `skillgate`。
