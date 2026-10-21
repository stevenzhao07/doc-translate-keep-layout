# 自测记录：中译英 · 保版式全链路

**日期**：2026-10-20　**样本**：合成的 7 段器械规格书片段（`examples/make_sample.py` 生成，含加粗标题、双 run 段落、法规号、单位）
**环境**：Python 3.13.12，纯标准库，零依赖

## 命令链（可原样重跑）

```bash
python examples/make_sample.py examples/sample.docx
python scripts/translate_kit.py map   examples/sample.docx -o examples/map.json
python scripts/translate_kit.py apply examples/sample.docx examples/plan.json -o examples/sample.en.docx
python scripts/translate_kit.py check examples/sample.docx examples/sample.en.docx -o examples/report.json
```

## 第 1 步：map 输出（节选）

7 个段落全部识别，第 5 段（`2.1 清洁验证` + 释义）`runs: 2` —— 正确暴露了段内双 run 的混排风险。

```
i=0  runs=1  chars=4   fmt=fcbfa4d7  "1 范围"
i=1  runs=1  chars=21  fmt=534e46c4  "本文件规定了胫骨冲击锉手柄的清洁验证要求。"
i=2  runs=1  chars=34  fmt=534e46c4  "适用于符合 MDR (EU) 2017/745 的 IIa 类器械。"
i=4  runs=2  chars=28  fmt=534e46c4  "2.1 清洁验证指通过检测残留物证明清洁工艺有效的过程。"
i=6  runs=1  chars=36  fmt=534e46c4  "残留限度应不超过 10 μg/cm²，内毒素应低于 0.5 EU/mL。"
```

## 第 2 步：回填

`apply` 成功写出 `sample.en.docx`。规则是「只换 `w:t` 文本、不重建 `w:r`」，所以 `w:rPr`（加粗、字号）原封不动。

## 第 3 步：check 输出（完整）

```json
{
  "para_delta": 0,
  "format_changed": [],
  "length_outliers": [],
  "median_ratio": 4.29,
  "chars_ratio": 2.93,
  "parts": {"word/document.xml": {"paras_before": 7, "paras_after": 7}}
}
```

三项硬指标全过：
- `para_delta = 0` → 段数没变，没被合并/拆分
- `format_changed = []` → 所有段落 run 数与首 run 格式签名都没变
- `length_outliers = []` → 没有段落相对全文异常膨胀

`chars_ratio 2.93` 是中译英的正常量级（中文字符数≈英文的 1/2~1/3），**不能**拿它当排版告警阈值——所以阈值用的是「相对全文中位数的偏离」，不是绝对值。

## 自测抓到的两个真 bug（已修）

1. **`paragraphs()` 把 run 列表当 count 返回** → `format_changed` 对每一段都误报「run 数变化」，第一版报告 7 条全红。
2. **膨胀阈值用绝对值 1.3** → 中译英必然全段超标，等于没告警。改成 `> max(1.8, 中位数 × 1.6)`，只在「这一段比全篇平均膨胀得多得多」时才报。

## 还没覆盖的（如实记）

- 表格内文字、页眉页脚、文本框、艺术字：当前不处理（**注**：表格单元格的段落其实能被 map 抽到，但单元格宽度固定、溢出风险高）
- PDF 输入：只出双语对照表，不保版式
- 段内多格式：回填后统一取第一段格式（样本第 5 段即为该情况，符合预期但需在交付时说明）

---

## 追加：真实器械文档冒烟测试（2026-10-20）

**文件**：`C:\Users\SZYL\Desktop\生物相容性测试方案.docx`（**只读副本操作，桌面原件未改动**）

| 项 | 实测值 |
|---|---|
| 段落总数（含空段与表格内段落） | 77 |
| 非空段落 | 63 |
| 字符总数 | 896 |
| run>2 的混排段 | 0 |
| 部分翻译范围 | 9 段（P1/P2/P5–P8/P19/P20/P48） |
| `para_delta` | 0 —— 含表格结构，段数没塌 |
| `format_changed` | `[]` |
| `chars_ratio` | 1.36（部分翻译，故低于全译的 2.9） |

### 第 3 个 bug（真实文档才暴露）

第一版跑出来 `length_outliers` 报了 4 条（ratio 2.09–3.04），看似告警正常，**其实是假的**：部分翻译时绝大多数段落没变、ratio=1.0，中位数被压成 1.0，于是每个「真的翻译过的段落」都被判成异常膨胀。

修法两条：
1. 中位数只在**文本真的变了**的段落上计算（`tb != ta`）；
2. 新增 `top_growth`：无论是否超标，恒返回涨幅前三，小样本下人也看得到最可疑的三段。

修后：`length_outliers = []`、`median_ratio = 2.33`、`top_growth` 首位 P5（ratio 3.04）。

### 真实风险点（交付时必须点名）

P5 原文 `适用器械：胫骨冲击锉手柄 / 关节置换手术工具`（23 字）译成英文后 70 字符，比值 3.04 —— 它在一个**固定宽度的表格单元格**里，极可能换行溢出。这类段落正是复核清单存在的意义。

