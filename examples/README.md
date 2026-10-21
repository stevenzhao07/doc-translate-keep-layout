# examples —— 可直接跑的样例产物

这里的文件都是 `v0.5.1` 实跑生成的，字段与当前版本一致。

| 文件 | 是什么 | 怎么来的 |
|---|---|---|
| `make_sample.py` | 生成一份最小 docx（含加粗前缀双 run 段、表格、编号） | 零依赖，直接 `python examples/make_sample.py 输出.docx` |
| `plan.json` | 翻译计划：单 run 段用字符串，双 run 段用 `{src,out}` 数组 | `map` 出 `run_texts` 后按 run 逐条填 |
| `report.json` | `check` 的输出（`verdict: clean`） | `check sample.docx sample.en.docx` |
| `gate-report-demo.json` | `gate` 的输出：**故意留一个术语冲突**，演示 `GATE-009` 阻断与 `evidence` 锚点 | 术语表里 `清洁验证 → cleaning validation` 标记已确认，而 plan 用占位译文 |

## 复现

```bash
cd <仓库根目录>
python examples/make_sample.py /tmp/sample.docx
python scripts/translate_kit.py map   /tmp/sample.docx -o /tmp/map.json
python scripts/translate_kit.py apply /tmp/sample.docx examples/plan.json --map /tmp/map.json -o /tmp/sample.en.docx
python scripts/translate_kit.py check /tmp/sample.docx /tmp/sample.en.docx -o /tmp/report.json
```

`plan.json` 里的译文是 `[EN] 原文` 形式的占位，**只用于验证流程，不是真译文**。要真翻译，把 `out` 字段换成目标语言。
