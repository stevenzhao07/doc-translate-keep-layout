# doc-translate-keep-layout

Translate `.docx` / `.pptx` without wrecking the layout — plus a terminology table, a layout review, and an audit trail you can check.

零依赖（Python 标准库），本地运行，不上传任何数据。

## 60 秒验证（先跑这条，再读别的）

```bash
# 1) 进入仓库根目录（以下命令都要求在这里执行）
cd doc-translate-keep-layout

# 2) 生成一份样例文档，跑通全链路（零依赖，Python 3.11+）
python examples/make_sample.py /tmp/sample.docx
python scripts/translate_kit.py map   /tmp/sample.docx -o /tmp/map.json
python scripts/translate_kit.py apply /tmp/sample.docx examples/plan.json --map /tmp/map.json -o /tmp/sample.en.docx
python scripts/translate_kit.py check /tmp/sample.docx /tmp/sample.en.docx -o /tmp/report.json

# 3) 自测：35 条回归用例
python tests/run_tests.py
```

> **Windows 提示**：若输出中文乱码（`璇戞枃` 这类），先执行 `chcp 65001` 或在 PowerShell 里设 `[Console]::OutputEncoding=[Text.Encoding]::UTF8`。
> 版本：`python scripts/translate_kit.py --version`。

## 它解决什么

翻文档最难的不是翻，是三件收尾的事：

1. **排版散了** —— 换字号、换字体、表格崩塌；
2. **术语前后不一致** —— 同一份文件里「浸提液 / 浸出液」混着用；
3. **没人知道哪里被撑爆了** —— 英文长句塞进固定宽度单元格，打印出来才发现。

这个工具把三件事分开做、分开交付，并在动手之前设一道 fail-closed 闸门。

## 四个子命令

```bash
python scripts/translate_kit.py map   in.docx -o map.json
python scripts/translate_kit.py gate  --map map.json --plan plan.json --terms 术语表.tsv --src in.docx -o gate.json
python scripts/translate_kit.py apply in.docx plan.json --map map.json --terms 术语表.tsv --gate gate.json -o out.en.docx
python scripts/translate_kit.py check in.docx out.en.docx -o report.json
```

> **`apply --gate gate.json` 是 fail-closed 的关键一环**：闸门报告不是 `pass` 时它直接拒绝回填（退出码 3）。不传 `--gate` 相当于自己拆掉了这道闸 —— 只在做结构验收时这么干。

| 命令 | 做什么 | 关键约束 |
|---|---|---|
| `map` | 抽段落：容器（body/table/txbx）、run 数、格式指纹、阻断因素、原文指纹 | 只取本段落直属 run，不吞文本框内嵌套段落 |
| `gate` | 译前闸门：漏译 / 越界 / 负索引 / 空值或同原文 / 未确认术语 / map 与源不符 | 阻断即退出码 1，不许进回填 |
| `apply` | 回填译文，只换文本不重建 run | 拒绝 src==out；含换行/超链接/修订/混排的段落默认不动 |
| `check` | 双向复核：段数差、清空、收缩、膨胀、格式变化 | 有问题即退出码 1 |

## 输入格式（第一次用就看这段）

**plan.json** —— 段号是**字符串**，值只能是字符串：

```json
{
  "parts": {
    "word/document.xml": {
      "0": "1 Scope",
      "5": "Applicable device: tibial impact broach handle"
    }
  }
}
```

段号来自 `map.json` 里每条记录的 `i`（**注意空段落也占号，所以 `i` 是跳号的**，别自己按 0,1,2 连续编）。

**值有三种写法**：

```json
"0": "1 Scope",                                   // 单 run 段落：直接给译文
"5": ["Figure 1:", "This is the body."],          // 多 run 段落：逐 run 译文（条数必须等于 run 数）
"8": [{"src": "警告：", "out": "WARNING:"},        // 推荐：带原文校验，顺序写反会被拦下
      {"src": "请勿口服。", "out": "Do not take orally."}]
```

- 段落有 **多个 run**（如「加粗前缀 + 正文」）时，**必须用数组**。给字符串会被拒绝（那会把整段格式压平）
- 纯字符串数组只能核对条数、**核对不了顺序**，闸门会给 `GATE-010` 提醒
- `{src, out}` 形式会逐条比对 `src` 与原 run 文字，**顺序错位直接拒绝**
- `run_texts` 里出现 `null` = 该 run 没有文本节点（图形/空壳），**这个位置不许写文字**

**术语表 TSV** —— 首行必须是表头，必需列 `源术语` / `状态`，建议带 `译法`：

```
源术语	译法	状态
清洁验证	cleaning validation	已确认
喷砂处理	sand blasting	待确认
```

- 编码：UTF-8，**带不带 BOM 都行**（Excel/记事本另存的 BOM 已兼容）
- `状态` 只能是三个值之一：`用户指定` / `已确认` / `待确认`，写别的会按未确认处理
- `待确认` 的词一旦出现在被翻译段落里 → 阻断；`已确认` 的词若译法没出现在译文里 → 也阻断（GATE-009）

## 退出码

| 码 | 含义 | 你该做什么 |
|---|---|---|
| 0 | 通过 | 继续下一步 |
| 1 | `gate`/`check` 有阻断项或待复核项 | 看报告里的 `blocking` / `missing` 等字段 |
| 2 | `apply` 有段落被跳过（结构不安全 / plan 对不上 / 值非法 / 数组条数不符） | 看屏幕上列出的段落号，人工处理 |
| 3 | 输入不可用（不是 docx、解压超限、0 段落、输出路径与源相同、**闸门报告不是 pass**） | 换文件或换路径，或先把闸门阻断面处理掉 |

审计记录 `audit.jsonl` 每行含：源/plan/map/术语表/产物五份 SHA-256、实际写入段数、跳过数、非法值数、**`forced`（哪些段是 `--force-unsafe` 强改的）**、`gate`（用了哪份闸门报告、结论如何）。

`check` 的 `grown`（膨胀超 3.5 倍）只作**提示**，不进退出码 —— 中译英天然会涨 3 倍，用绝对阈值会天天误报。真正判红的是 `missing` / `extra` / `format_changed` / `emptied` / `shrunk` / **`untranslated`（原文有中文、译文一字未改）**。

## 三条设计原则

1. **能停就停，不要猜。** 术语没确认、段落含超链接、原文被改过 —— 一律阻断，不"尽力而为"。
2. **坏掉的时候要响。** 一段没写进去、译文被清空、段落少了一段，都必须报错退出，而不是打印 `written:` 就走。
3. **每一步留痕。** 源文件 / plan / map / 术语表 / 产物，五份 SHA-256 写进 `audit.jsonl`（传了 `--terms` 才有第五份）。

## 已知限制（照实写）

- **PDF 不保版式**：PDF 无段落结构，本工具只处理 docx/pptx。
- **段内混排**：需要**逐 run 译文数组**（`map` 会给 `run_texts`）。给字符串会被拒绝。`--force-unsafe` 可以强改，但会把整段压成一个格式 —— 那是毁格式，不是修复。
- **超链接 / 换行 / 制表 / 修订痕迹**：默认跳过（会破坏结构），需人工处理。
- **表格单元格**：能处理，但单元格宽度按中文排的，英文长句必挤 —— `check` 会报膨胀，调列宽是人工活。
- **命名空间**：`mc:Ignorable` 引用的前缀会在回填后自动补回声明；但只出现在属性值里的自定义命名空间仍可能丢（元数据级差异，正文不受影响）。
- **并发**：`audit.jsonl` 无锁，多进程同时写会交错。

## 自测

```bash
python tests/run_tests.py      # 32 条回归用例，当前 32/32
```

用例覆盖：自我覆盖防护、plan 与文档错位、混排拒绝（含「第二个 run 无 rPr」隐蔽变体）、**逐 run 对齐保格式**、**顺序写反被拦**、**纯数组顺序不可校验时会告警**、**首 run 是图形时不静默抹字**、超链接/换行标记、文本框不重复计数、负索引、空值/同原文、假 map、术语表缺失 fail-closed、**术语表 BOM 兼容**、**译法不一致拦截**、韩文不免译、.docm 识别、Strict OOXML 不静默、空文档不静默、**mc:Ignorable 处理**、pptx 支持、**该翻没翻会被 check 抓**、**pPr 制表位不误判**、清空与收缩检测、坏 zip、解压炸弹。

测试产物写到系统临时目录，**不会污染技能包目录**。

## 许可

代码 MIT。`references/terminology.md` 与 `SKILL.md` 中的方法描述同属 MIT。
