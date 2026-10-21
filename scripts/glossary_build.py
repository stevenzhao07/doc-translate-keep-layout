#!/usr/bin/env python3
"""glossary_build — 从一堆 docx/pptx 里抽「术语候选」，产出待人工确认的术语表底稿。

纯标准库，只读不写原文件；输出两个文件：
  术语候选.tsv   候选词 / 频次 / 覆盖文档数 / 示例上下文
  语料统计.md    扫了多少文件、多少字、哪些跳过

用法：
  python glossary_build.py --dir "D:\\骨科文档" --out "D:\\out" --min-freq 3 --min-docs 2
"""
import argparse
import collections
import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import translate_kit as tk

CJK_RUN = re.compile(r"[\u4e00-\u9fff]{2,}")
LATIN_TOKEN = re.compile(r"\b(?:ISO|GB/T|GB|ASTM|UNS|YY/T|MDR|IVDR|FDA|NMPA|CMDE|IEC)\s?[A-Za-z0-9][A-Za-z0-9.\-:/ ]{0,18}")
# 按功能字切分，切出来的片段才像「词」而不是任意 n-gram
FUNC = "的了和与及或为是在对按从以等之其该本并且但则若如将已还由中上下内外把被后再做经需应须于至到向使让给而即就都也更较最很未"
SPLIT = re.compile(f"[{FUNC}]")
MIN_LEN, MAX_LEN = 2, 12
# 通用高频词不是术语，先剔掉，剩下的交人工确认
GENERIC = {
    "使用", "方法", "分析", "应用", "要求", "内容", "能力", "技术", "部分", "基础",
    "具有", "采用", "详细", "状态", "类型", "背景", "方案", "过程", "历史", "建立",
    "指标", "流程", "情况", "工作", "问题", "数据", "系统", "管理", "产品", "相关",
    "进行", "包括", "主要", "一般", "可以", "需要", "同时", "以及", "以上", "以下",
    "研究", "实现", "设计", "基于", "开发", "建设", "提出", "提高", "完成", "通过",
    "阶段", "模式", "环节", "方面", "目标", "特点", "关键", "重要性", "必要性", "可行性",
    "个月", "第一", "第二", "第三", "本文", "本章", "如表", "如图", "如下", "上述",
}


TEXT_EXT = (".txt", ".md", ".markdown", ".csv", ".tsv")
OFFICE_EXT = (".docx", ".pptx")


def doc_text(path):
    kind = tk.parts_of(path)
    chunks = []
    with zipfile.ZipFile(path) as zf:
        for part in tk.part_list(zf, kind):
            try:
                root = ET.fromstring(zf.read(part))
            except ET.ParseError:
                continue
            for item in tk.paragraphs(root, kind):
                if item["text"].strip():
                    chunks.append(item["text"])
    return "\n".join(chunks)


def read_any(path):
    """office 文件走 XML 抽文本；纯文本（知识库导出件）直接读，自动兼容 UTF-8/GBK。"""
    if path.lower().endswith(OFFICE_EXT):
        return doc_text(path)
    raw = open(path, "rb").read()
    for enc in ("utf-8", "utf-8-sig", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


def collect(text, grams, docs, ctx, doc_id):
    for m in CJK_RUN.finditer(text):
        run = m.group(0)
        pos = m.start()
        cursor = 0
        for frag in SPLIT.split(run):
            start = pos + cursor
            cursor += len(frag) + 1
            if MIN_LEN <= len(frag) <= MAX_LEN:
                grams[frag] += 1
                docs[frag].add(doc_id)
                if frag not in ctx:
                    s = max(0, start - 8)
                    ctx[frag] = text[s:start + len(frag) + 12].replace("\n", " ")
    for m in LATIN_TOKEN.finditer(text):
        g = m.group(0).strip()
        if len(g) >= 5:
            grams[g] += 1
            docs[g].add(doc_id)
            ctx.setdefault(g, text[max(0, m.start() - 8):m.end() + 8].replace("\n", " "))


def maximal(grams, docs, min_freq, min_docs):
    cand = [(g, c) for g, c in grams.items()
            if c >= min_freq and len(docs[g]) >= min_docs and g not in GENERIC]
    cand.sort(key=lambda x: (-len(x[0]), -x[1]))
    kept = []
    for g, c in cand:
        if any(g != k and g in k and grams[k] >= c * 0.8 for k, _ in kept):
            continue
        kept.append((g, c))
    kept.sort(key=lambda x: (-len(docs[x[0]]), -(x[1] * len(x[0])), -x[1]))
    return kept


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, help="要扫的文件夹（递归）")
    ap.add_argument("--out", required=True, help="输出目录")
    ap.add_argument("--min-freq", type=int, default=3)
    ap.add_argument("--min-docs", type=int, default=2)
    ap.add_argument("--top", type=int, default=300)
    a = ap.parse_args()

    os.makedirs(a.out, exist_ok=True)
    grams = collections.Counter()
    docs = collections.defaultdict(set)
    ctx = {}
    done, skipped, total_chars = [], [], 0

    targets = [a.dir] if os.path.isfile(a.dir) else [
        os.path.join(r, fn) for r, _, fs in os.walk(a.dir) for fn in fs
    ]
    for p in targets:
        low = p.lower()
        if low.endswith(OFFICE_EXT + TEXT_EXT):
            try:
                text = read_any(p)
            except Exception as e:
                skipped.append((p, f"解析失败: {e}"))
                continue
            if not text.strip():
                skipped.append((p, "无文本（可能是扫描件/纯图片）"))
                continue
            collect(text, grams, docs, ctx, p)
            done.append((p, len(text)))
            total_chars += len(text)
        elif low.endswith((".doc", ".pdf", ".xlsx")):
            skipped.append((p, "暂不支持（.doc/.pdf/.xlsx 需先转 docx，或从知识库导出为 txt/md）"))

    kept = maximal(grams, docs, a.min_freq, a.min_docs)[:a.top]

    tsv = os.path.join(a.out, "术语候选.tsv")
    with open(tsv, "w", encoding="utf-8") as f:
        f.write("候选\t频次\t覆盖文档数\t示例上下文\n")
        for g, c in kept:
            f.write(f"{g}\t{c}\t{len(docs[g])}\t{ctx.get(g, '')}\n")

    stat = os.path.join(a.out, "语料统计.md")
    with open(stat, "w", encoding="utf-8") as f:
        f.write("# 语料统计\n\n")
        f.write(f"- 扫描根目录：`{a.dir}`\n")
        f.write(f"- 成功解析：**{len(done)}** 个文档，共 {total_chars:,} 字\n")
        f.write(f"- 跳过：**{len(skipped)}** 个\n")
        f.write(f"- 候选术语：**{len(kept)}** 条（频次≥{a.min_freq} 且覆盖≥{a.min_docs} 个文档）\n\n")
        if skipped:
            f.write("## 跳过清单\n\n| 文件 | 原因 |\n|---|---|\n")
            for p, why in skipped[:80]:
                f.write(f"| {os.path.basename(p)} | {why} |\n")
            if len(skipped) > 80:
                f.write(f"\n（其余 {len(skipped) - 80} 条略）\n")
    print(f"docs={len(done)} skipped={len(skipped)} candidates={len(kept)} -> {tsv}")


if __name__ == "__main__":
    main()
