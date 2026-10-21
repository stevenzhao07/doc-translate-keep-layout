#!/usr/bin/env python3
"""translate_kit v0.5.2 — 文档翻译三件底层工具（纯标准库，零依赖）。

子命令：
  map   提取 docx/pptx 段落：文本、容器、格式指纹、不可自动回填的阻断因素 → JSON
  apply 按 JSON 把译文写回：只换文本不动 run；拒绝破坏结构；写 audit 记录
  check 对比原文/译文结构：双向膨胀/收缩、段数差、清空、格式变化
  gate  译前闸门（fail-closed）：漏译 / 越界 / 负索引 / 空值 / 未确认术语 / map 与源不符

v0.3.0 相对 v0.2.0 的修复（红队评审驱动）：
  - apply 拒绝 src == out（旧版会销毁原件，且审计自证"源=产物"）
  - apply 支持/建议 --map，逐段比对原文，防"plan 与文档错位后静默写错"
  - 段落文本只取本段落直属 run，不再吞掉文本框内嵌套段落（旧版重复计数 + 重复写入）
  - 含换行/制表/超链接/修订/嵌套段落/混排的段落标 blockers，默认拒绝自动回填
  - 负索引拒绝；空值/同原文值拒绝；实际写入段数为 0 时报错
  - 未改动的 zip 条目流式复制，并对解压总大小设上限（防内存放大）
  - gate 会校验 plan 的"值"，并可用 --src 重算 map 与 --map 交叉核对
  - terms 文件不存在时 fail-closed；状态按枚举精确匹配
  - check 双向判据（收缩也报）、短段纳入、空译文单列、段数差列出缺失段落
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

VERSION = "0.5.2"
MAX_UNZIP_BYTES = 300 * 1024 * 1024  # 解压总量上限，超了直接拒绝

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
XML = "http://www.w3.org/XML/1998/namespace"
CT_NS = "{http://schemas.openxmlformats.org/package/2006/content-types}"

for uri, pref in {
    W: "w",
    A: "a",
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships": "r",
    "http://schemas.openxmlformats.org/drawingml/2006/picture": "pic",
    "http://schemas.openxmlformats.org/presentationml/2006/main": "p",
    "http://schemas.openxmlformats.org/markup-compatibility/2006": "mc",
    "urn:schemas-microsoft-com:office:office": "o",
    "urn:schemas-microsoft-com:office:word": "w10",
    "http://schemas.microsoft.com/office/word/2010/wordml": "w14",
    "http://schemas.openxmlformats.org/package/2006/relationships": "pr",
    "http://schemas.openxmlformats.org/package/2006/content-types": "ct",
}.items():
    ET.register_namespace(pref, uri)

W_P, W_T, W_R, W_RPR = f"{{{W}}}p", f"{{{W}}}t", f"{{{W}}}r", f"{{{W}}}rPr"
A_P, A_T, A_R, A_RPR = f"{{{A}}}p", f"{{{A}}}t", f"{{{A}}}r", f"{{{A}}}rPr"
W_TBL, W_TC, W_TXBX = f"{{{W}}}tbl", f"{{{W}}}tc", f"{{{W}}}txbxContent"
W_BR, W_TAB, W_HYPERLINK = f"{{{W}}}br", f"{{{W}}}tab", f"{{{W}}}hyperlink"
W_INS, W_DEL = f"{{{W}}}ins", f"{{{W}}}del"
CJK = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]")


# ---------- 基础 ----------

def tags(kind):
    return (W_P, W_T, W_R, W_RPR) if kind == "docx" else (A_P, A_T, A_R, A_RPR)


def detect_kind(path):
    """按 [Content_Types].xml 判真实类型，而不是只看扩展名（.docm/.dotx 都算 docx）。"""
    try:
        with zipfile.ZipFile(path) as zf:
            ct = zf.read("[Content_Types].xml").decode("utf-8", "ignore")
    except Exception:
        return None
    if "wordprocessingml" in ct:
        return "docx"
    if "presentationml" in ct:
        return "pptx"
    return None


def part_list(zf, kind):
    if kind == "docx":
        return ["word/document.xml"]
    return sorted(n for n in zf.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n))


def sig(el):
    return "" if el is None else hashlib.md5(ET.tostring(el, encoding="utf-8")).hexdigest()[:8]


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _tsig(text):
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:12]


def _snip(text, n=40):
    s = (text or "").replace("\n", " ")
    return s if len(s) <= n else s[:n] + "…"


def _fix_ns(orig_bytes, out_bytes):
    """处理 mc:Ignorable 与命名空间声明脱钩的问题。

    做法是**删掉**已无声明的前缀引用（而不是补声明）：
    ElementTree 不会保留"只出现在属性值里"的命名空间，补声明要精确插入根标签，
    插错位置（比如插进 XML 声明里）会直接产出非法 XML —— 删引用永远合法。
    """
    txt = out_bytes.decode("utf-8")
    m = re.search(r'mc:Ignorable="([^"]*)"', txt)
    if not m:
        return out_bytes
    prefixes = m.group(1).split()
    keep = [p for p in prefixes if f"xmlns:{p}=" in txt]
    if keep == prefixes:
        return out_bytes
    new_attr = ('mc:Ignorable="' + " ".join(keep) + '"') if keep else ""
    txt = txt.replace(m.group(0), new_attr)
    if not keep:  # 全删就顺手清掉多余空格
        txt = re.sub(r'\s+>', '>', txt)
    return txt.encode("utf-8")


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_plan(path):
    """plan 只认 {'parts': {...}} 一种形状；两种写法混着接受是 bug 温床。"""
    d = load_json(path)
    if isinstance(d, dict) and "parts" in d:
        return d["parts"]
    raise ValueError("plan 必须是 {'parts': {<part>: {'<段号>': '<译文>'}}} 结构")


def iter_paras(root, kind):
    """返回 [(段落元素, 容器)]；容器 body/table/txbx，嵌套段落各自单独一条。"""
    p_tag = tags(kind)[0]
    out = []

    def rec(node, container):
        for ch in list(node):
            t = ch.tag
            if t in (W_TBL, W_TC):
                rec(ch, "table")
            elif t == W_TXBX:
                rec(ch, "txbx")
            elif t == p_tag:
                out.append((ch, container))
                rec(ch, container)
            else:
                rec(ch, container)

    rec(root, "body")
    return out


def para_detail(p, kind):
    """按 run 分组取文本；区分"能写文字的 run"与"空壳 run"。

    阻断因素只反映"本段落自身的 run 会被覆盖破坏"：
      - 跳过 w:pPr / w:rPr / w:sectPr 整棵（那些是属性，不是内容：目录的 tabs 定义、段落标记修订都在这）
      - w:txbxContent 整棵跳过且不记阻断（框内段落由 iter_paras 单独成条，不该连坐外层）
      - 嵌套 w:p 同样跳过且不记阻断
    """
    p_tag, t_tag, r_tag, rpr_tag = tags(kind)
    run_ts, blockers = [], set()
    SKIP = {f"{{{W}}}pPr", f"{{{W}}}rPr", f"{{{W}}}sectPr", W_TXBX}
    FIELD = {f"{{{W}}}fldChar", f"{{{W}}}instrText", f"{{{W}}}fldSimple",
             f"{{{W}}}footnoteReference", f"{{{W}}}endnoteReference"}

    def in_run(r):
        out = []

        def rec(n):
            for ch in list(n):
                t = ch.tag
                if t in SKIP or t == p_tag:
                    continue  # 文本框/嵌套段落里的文字不属于本 run
                if t == t_tag:
                    out.append(ch)
                elif t in FIELD:
                    blockers.add("field")
                elif t == W_BR:
                    blockers.add("line-break")
                elif t == W_TAB:
                    blockers.add("tab")
                rec(ch)

        rec(r)
        return out

    def rec(n):
        for ch in list(n):
            t = ch.tag
            if t in SKIP or t == p_tag:
                continue
            # 结构标记必须在"任何层级"都被看见：超链接常常包着 run
            if t == W_HYPERLINK:
                blockers.add("hyperlink")
            elif t in (W_INS, W_DEL):
                blockers.add("revision")
            elif t in FIELD:
                blockers.add("field")
            elif t == W_BR:
                blockers.add("line-break")
            elif t == W_TAB:
                blockers.add("tab")
            if t == r_tag:
                run_ts.append(in_run(ch))
                continue
            rec(ch)

    rec(p)
    # rPr 只取直属 run（不含嵌套段落内的）
    def direct_runs(n):
        for ch in list(n):
            if ch.tag in SKIP or ch.tag == p_tag:
                continue
            if ch.tag == r_tag:
                yield ch
            else:
                yield from direct_runs(ch)

    run_rpr = [sig(r.find(rpr_tag)) for r in direct_runs(p)]
    if len(run_rpr) > 1 and len(set(run_rpr)) > 1:
        blockers.add("mixed-format")
    run_texts = ["".join(t.text or "" for t in ts) if ts else None for ts in run_ts]
    return {
        "run_ts": run_ts,
        "run_texts": run_texts,
        "writable": sum(1 for ts in run_ts if ts),
        "text": "".join(t for t in run_texts if t),
        "runs": len(run_ts),
        "fmt": run_rpr[0] if run_rpr else "",
        "blockers": sorted(blockers),
    }


def _fill(ts, text):
    """把文字写进某个 run 的 w:t。写不了（无 w:t 节点）返回 False，绝不假装成功。"""
    if not ts:
        return False
    ts[0].text = text
    ts[0].set(f"{{{XML}}}space", "preserve")
    for t in ts[1:]:
        t.text = ""
    return True


def build_map(root, kind):
    rows = []
    paras = iter_paras(root, kind)
    for i, (p, container) in enumerate(paras):
        d = para_detail(p, kind)
        if not d["text"].strip():
            continue
        rows.append({"i": i, "container": container, "runs": d["runs"], "writable": d["writable"],
                     "chars": len(d["text"]), "fmt": d["fmt"], "blockers": d["blockers"],
                     "tsig": _tsig(d["text"]), "text": d["text"]})
        if d["runs"] > 1:
            rows[-1]["run_texts"] = d["run_texts"]  # null = 该 run 没有文本节点，写不进去
    return rows, len(paras)


def _emit(obj, out):
    blob = json.dumps(obj, ensure_ascii=False, indent=2)
    if out:
        with open(out, "w", encoding="utf-8") as f:
            f.write(blob)
        print(f"written: {out}")
    else:
        print(blob)


# ---------- map ----------

def cmd_map(args):
    kind = detect_kind(args.src)
    if kind is None:
        print(f"错误：{args.src} 不是可识别的 docx/pptx（[Content_Types].xml 里没有 wordprocessingml/presentationml）")
        return 3
    data = {"kind": kind, "tool_version": VERSION, "src": os.path.abspath(args.src),
            "src_sha256": _sha(args.src), "parts": {}}
    if sum(i.file_size for i in zipfile.ZipFile(args.src).infolist()) > MAX_UNZIP_BYTES:
        print("错误：解压后体积超过上限")
        return 3
    with zipfile.ZipFile(args.src) as zf:
        for part in part_list(zf, kind):
            if part not in zf.namelist():
                print(f"错误：缺少主部件 {part}")
                return 3
            root = ET.fromstring(zf.read(part))
            rows, total = build_map(root, kind)
            if total == 0:
                print(f"错误：{part} 里解析出 0 个段落。可能是 Strict OOXML（purl.oclc.org 命名空间）"
                      f"或非 Word 生成的文档；本工具不假装成功。")
                return 3
            data["parts"][part] = rows
            data.setdefault("meta", {})[part] = {"total_paras": total, "nonempty": len(rows)}
    _emit(data, args.out)
    return 0


# ---------- apply ----------

def cmd_apply(args):
    src_abs, out_abs = os.path.abspath(args.src), os.path.abspath(args.out)
    if src_abs == out_abs:
        print("错误：输出路径与源文件相同，拒绝执行（会销毁原件）")
        return 3
    gate_info = None
    if args.gate:
        # 闸门没过就别回填 —— 否则"fail-closed"只是一句口号，一个参数就能绕过去
        if not os.path.exists(args.gate):
            print(f"错误：闸门报告不存在：{args.gate}")
            return 3
        rep = load_json(args.gate)
        gate_info = {"path": os.path.abspath(args.gate), "gate": rep.get("gate"),
                     "blocking": len(rep.get("blocking") or [])}
        if rep.get("gate") != "pass":
            print(f"错误：闸门报告是 {rep.get('gate')}（{gate_info['blocking']} 条阻断），拒绝回填")
            for b in (rep.get("blocking") or [])[:6]:
                print(f"  x [{b.get('rule_id')}] {b.get('type')}: {b.get('term', '')} "
                      f"{b.get('why', '')} {b.get('paras', '')}")
            return 3
    kind = detect_kind(args.src)
    if kind is None:
        print("错误：源文件不是可识别的 docx/pptx")
        return 3
    try:
        per_part = load_plan(args.plan)
    except ValueError as e:
        print(f"错误：{e}")
        return 3

    src_sha = _sha(args.src)  # 必须在写之前算
    verify = None
    if args.map:
        verify = {p: {str(r["i"]): r["tsig"] for r in rows}
                  for p, rows in load_json(args.map).get("parts", {}).items()}

    written = 0
    skipped_unsafe, skipped_verify, bad_values, forced = [], [], [], []
    with zipfile.ZipFile(args.src) as zin:
        total = sum(i.file_size for i in zin.infolist())
        if total > MAX_UNZIP_BYTES:
            print(f"错误：解压后 {total/1048576:.0f} MB 超过上限 {MAX_UNZIP_BYTES//1048576} MB")
            return 3
        replacements = {}
        for part, mapping in per_part.items():
            if part not in zin.namelist():
                print(f"错误：源文件里没有 {part}")
                return 3
            raw = zin.read(part)
            root = ET.fromstring(raw)
            paras = iter_paras(root, kind)
            if not paras:
                print(f"错误：{part} 里解析出 0 个段落，拒绝输出（会成为一份看起来成功的空翻译）")
                return 3
            for key, val in mapping.items():
                try:
                    idx = int(key)
                except ValueError:
                    bad_values.append({"key": key, "why": "段落号不是整数"})
                    continue
                if not (0 <= idx < len(paras)):
                    bad_values.append({"key": key, "why": "段落号越界或为负"})
                    continue
                if not isinstance(val, (str, list)):
                    bad_values.append({"key": key, "why": "译文必须是字符串或字符串数组"})
                    continue
                if isinstance(val, str) and not val.strip():
                    bad_values.append({"key": key, "why": "译文为空"})
                    continue
                p = paras[idx][0]
                d = para_detail(p, kind)
                if verify and part in verify:
                    if verify[part].get(str(idx)) != _tsig(d["text"]):
                        skipped_verify.append({"part": part, "para": idx,
                                               "why": "原文已被改动或 plan 与文档不匹配"})
                        continue
                hard = [b for b in d["blockers"]
                        if b in ("hyperlink", "line-break", "tab", "revision",
                                 "textbox", "nested-paragraph")]
                if d["blockers"] and hard and not args.force_unsafe:
                    skipped_unsafe.append({"part": part, "para": idx, "blockers": hard})
                    continue
                if hard and args.force_unsafe:
                    forced.append({"part": part, "para": idx, "blockers": hard})
                if isinstance(val, list):
                    # 逐 run 对齐：条数 = run 数；空壳 run 位必须为 null/空；
                    # 元素可以是 {"src","out"} —— 此时逐条校验 src 与原 run 文本一致，
                    # 防"顺序写反"这种条数正确但内容错位的情况。
                    if len(val) != len(d["run_ts"]):
                        bad_values.append({"key": key,
                                           "why": f"逐 run 译文 {len(val)} 条 ≠ 原文 run {len(d['run_ts'])} 个"})
                        continue
                    plan_items = []
                    bad = None
                    for i, (item, cur) in enumerate(zip(val, d["run_texts"])):
                        if cur is None:  # 空壳 run：不接受任何文字
                            if item not in (None, ""):
                                bad = f"第 {i} 个 run 没有文本节点，不能写入"
                            continue
                        if isinstance(item, dict):
                            src = item.get("src")
                            out = item.get("out")
                            if src is not None and src != cur:
                                bad = f"第 {i} 个 run 原文对不上（plan 写「{src}」，实际「{cur}」）"
                                break
                            if not isinstance(out, str) or not out.strip():
                                bad = f"第 {i} 个 run 译文为空"
                                break
                            plan_items.append((i, out))
                        elif isinstance(item, str) and item.strip():
                            plan_items.append((i, item))
                        elif item in (None, ""):
                            bad = f"第 {i} 个 run 有原文「{cur}」却没有译文"
                            break
                        else:
                            bad = f"第 {i} 个 run 译文类型不对"
                            break
                    if bad:
                        bad_values.append({"key": key, "why": bad})
                        continue
                    for i, text in plan_items:
                        _fill(d["run_ts"][i], text)
                    written += 1
                    continue
                # 字符串路径：只允许"恰好一个可写 run"的段落，否则就是在压缩格式
                if d["writable"] > 1:
                    bad_values.append({"key": key,
                                       "why": f"该段有 {d['writable']} 个可写 run，字符串会把格式压成一个；"
                                              f"请用逐 run 数组（map 里有 run_texts）"})
                    continue
                if d["writable"] == 0:
                    bad_values.append({"key": key, "why": "该段没有可写文本节点"})
                    continue
                first = next(i for i, ts in enumerate(d["run_ts"]) if ts)
                if not _fill(d["run_ts"][first], val):
                    bad_values.append({"key": key, "why": "写入失败"})
                    continue
                for i, rts in enumerate(d["run_ts"]):  # 其余空壳 run 保持原样
                    if i != first:
                        for t in rts:
                            t.text = ""
                written += 1
            replacements[part] = _fix_ns(raw, ET.tostring(root, encoding="utf-8", xml_declaration=True))

        if written == 0:
            print("错误：一段都没有真正写入（检查 plan 与文档是否对应、是否全部被阻断）")
            _emit({"written": 0, "bad_values": bad_values[:20], "skipped_unsafe": skipped_unsafe[:20],
                   "skipped_verify": skipped_verify[:20]}, None)
            return 2

        with zipfile.ZipFile(args.out, "w", zipfile.ZIP_DEFLATED) as zout:
            for info in zin.infolist():
                if info.filename in replacements:
                    zout.writestr(info, replacements[info.filename])
                else:  # 未改动的条目流式复制，不整包读进内存
                    with zin.open(info) as s, zout.open(info, "w") as d:
                        shutil.copyfileobj(s, d)

    rec = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tool": {"name": "translate_kit", "version": VERSION,
                 "src_sha256": src_sha, "src": src_abs,
                 "plan_sha256": _sha(args.plan), "plan": os.path.abspath(args.plan),
                 "map_sha256": _sha(args.map) if args.map else None,
                 "terms_sha256": _sha(args.terms) if args.terms and os.path.exists(args.terms) else None,
                 "out_sha256": _sha(args.out), "out": out_abs},
        "paragraphs_written": written,
        "paragraphs_skipped_unsafe": len(skipped_unsafe),
        "paragraphs_skipped_verify": len(skipped_verify),
        "bad_values": len(bad_values),
        "forced": forced,
        "gate": gate_info,
    }
    log = os.path.join(os.path.dirname(out_abs) or ".", "audit.jsonl")
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(f"written: {args.out}  paragraphs_written={written} "
          f"skipped_unsafe={len(skipped_unsafe)} skipped_verify={len(skipped_verify)} "
          f"bad_values={len(bad_values)} forced={len(forced)}")
    if forced:
        print(f"警告：{len(forced)} 段是在 --force-unsafe 下强改的，结构可能已被破坏（已记入 audit）")
    print(f"audit:   {log}")
    if skipped_unsafe or skipped_verify or bad_values:
        _emit({"skipped_unsafe": skipped_unsafe[:20], "skipped_verify": skipped_verify[:20],
               "bad_values": bad_values[:20]}, None)
        if skipped_unsafe and not args.force_unsafe:
            print("提示：含换行/超链接/修订/域/混排的段落需要人工处理；确需强改加 --force-unsafe")
            return 2
        if bad_values:
            print("提示：有段落因 plan 不合法被跳过（见 bad_values），请修正后重跑")
            return 2
    return 0


# ---------- check ----------

def cmd_check(args):
    kind = detect_kind(args.src)
    if kind is None:
        print("错误：源文件不是可识别的 docx/pptx")
        return 3
    report = {"src": os.path.abspath(args.src), "dst": os.path.abspath(args.dst),
              "tool_version": VERSION, "para_delta": {}, "missing": [], "extra": [],
              "format_changed": [], "shrunk": [], "emptied": [], "grown": [],
              "untranslated": [], "chars_ratio": 0, "top_growth": []}
    with zipfile.ZipFile(args.src) as za, zipfile.ZipFile(args.dst) as zb:
        tot_a = tot_b = 0
        growth = []
        for part in part_list(za, kind):
            ra = build_map(ET.fromstring(za.read(part)), kind)[0]
            rb = build_map(ET.fromstring(zb.read(part)), kind)[0]
            da, db = {r["i"]: r for r in ra}, {r["i"]: r for r in rb}
            report["para_delta"][part] = len(rb) - len(ra)
            for i in sorted(set(da) - set(db)):
                report["missing"].append({"part": part, "para": i, "text": _snip(da[i]["text"])})
            for i in sorted(set(db) - set(da)):
                report["extra"].append({"part": part, "para": i, "text": _snip(db[i]["text"])})
            for i in sorted(set(da) & set(db)):
                a, b = da[i], db[i]
                tot_a += len(a["text"])
                tot_b += len(b["text"])
                if a["runs"] != b["runs"] or a["fmt"] != b["fmt"]:
                    report["format_changed"].append({"part": part, "para": i,
                                                     "runs": [a["runs"], b["runs"]]})
                if not b["text"].strip():
                    report["emptied"].append({"part": part, "para": i, "src": _snip(a["text"])})
                    continue
                if a["text"] == b["text"]:
                    if CJK.search(a["text"]):  # 原文有中文、译文一字未改 = 没翻
                        report["untranslated"].append({"part": part, "para": i,
                                                       "text": _snip(a["text"])})
                    continue
                ratio = round(len(b["text"]) / max(len(a["text"]), 1), 2)
                growth.append({"part": part, "para": i, "ratio": ratio, "text": _snip(b["text"])})
                if ratio < 0.5:
                    report["shrunk"].append(growth[-1])
        report["chars_ratio"] = round(tot_b / max(tot_a, 1), 2)
        # 绝对判据：中译英经验上限 3.5；超过即报，不再用中位数倍数（中位数本身就在 3 左右）
        report["grown"] = [g for g in growth if g["ratio"] > 3.5]
        report["top_growth"] = sorted(growth, key=lambda g: -g["ratio"])[:5]
    ok = (not report["missing"] and not report["extra"] and not report["format_changed"]
          and not report["emptied"] and not report["shrunk"] and not report["untranslated"])
    report["verdict"] = "clean" if ok else "review"
    _emit(report, args.out)
    print(f"CHECK={report['verdict']} missing={len(report['missing'])} extra={len(report['extra'])} "
          f"format_changed={len(report['format_changed'])} emptied={len(report['emptied'])} "
          f"untranslated={len(report['untranslated'])} "
          f"shrunk={len(report['shrunk'])} grown={len(report['grown'])} chars_ratio={report['chars_ratio']}")
    return 0 if ok else 1


# ---------- gate ----------

RULES = {
    "漏译": ("GATE-001", "原文含文字（中日韩）的段落在 plan 中缺失"),
    "越界或非整数编号": ("GATE-002", "plan 中的段落号不在合法范围"),
    "待确认术语被翻译": ("GATE-003", "术语表状态为「待确认」的词出现在被翻译段落"),
    "免译段落": ("GATE-004", "原文不含中日韩字符，本无需翻译"),
    "译文为空或同原文": ("GATE-005", "plan 的值为空、非字符串，或与原文完全相同"),
    "map 与源文档不符": ("GATE-006", "map 里的原文指纹与 --src 实际内容不一致"),
    "术语表不可用": ("GATE-007", "术语表文件缺失、表头不合规或编码异常"),
    "不可自动回填": ("GATE-008", "该段含换行/超链接/修订/混排，apply 会拒绝，需人工处理"),
    "译法不一致": ("GATE-009", "已确认术语的译法没有出现在该段译文里"),
    "逐 run 顺序未校验": ("GATE-010", "逐 run 译文用的是纯字符串数组，顺序只能靠人保证"),
    "逐 run 原文不符": ("GATE-011", "{src,out} 里的 src 与该 run 的实际原文不一致（顺序错位）"),
}

STATUS_ENUM = ("用户指定", "已确认", "待确认")
BLOCKING_KINDS = {"漏译", "越界或非整数编号", "待确认术语被翻译", "译文为空或同原文",
                  "map 与源文档不符", "术语表不可用", "不可自动回填", "译法不一致",
                  "逐 run 原文不符"}


def read_terms(path):
    """按表头定位列；utf-8-sig 兼容 BOM；找不到必需列 → 抛错（宁可不跑，不静默关掉检查）。"""
    with open(path, encoding="utf-8-sig") as f:
        lines = [l for l in f.read().splitlines() if l.strip()]
    if not lines:
        raise ValueError("术语表为空")
    head = [h.strip().lstrip("\ufeff") for h in lines[0].split("\t")]
    need = {"源术语", "状态"}
    if not need.issubset(set(head)):
        raise ValueError("术语表缺少必需列：%s（当前表头：%s）"
                         % ("、".join(need - set(head)), " / ".join(head)))
    it, ist = head.index("源术语"), head.index("状态")
    itr = next((i for i, h in enumerate(head) if "译" in h), None)
    rows = []
    for line in lines[1:]:
        c = line.split("\t")
        if len(c) > max(it, ist) and c[it].strip():
            rows.append((c[it].strip(),
                         c[itr].strip() if itr is not None and len(c) > itr else "",
                         c[ist].strip()))
    return rows


def plan_text(pv):
    """把 plan 值统一成"译文全文"：字符串 / 字符串数组 / {src,out} 数组都支持。
    gate 与 apply 必须共用这一处，否则两边对同一份 plan 的判断会不一致（v0.5.0 的教训）。"""
    if isinstance(pv, str):
        return pv
    if isinstance(pv, list):
        parts = []
        for x in pv:
            if isinstance(x, str):
                parts.append(x)
            elif isinstance(x, dict):
                parts.append(x.get("out") or "")
        return "".join(parts)
    return ""


def plan_value_error(pv, runs=None):
    """返回该 plan 值的结构错误说明（None 表示合规）。"""
    if isinstance(pv, str):
        return None if pv.strip() else "译文为空"
    if isinstance(pv, list):
        if runs is not None and len(pv) != runs:
            return f"逐 run 译文 {len(pv)} 条 ≠ 原文 run {runs} 个"
        for i, x in enumerate(pv):
            if isinstance(x, dict):
                if not isinstance(x.get("out"), str) or not x.get("out").strip():
                    return f"第 {i} 条缺少 out 译文"
            elif isinstance(x, str):
                if runs is not None and x == "":
                    continue  # 空壳 run 位允许空串
                if not x.strip() and runs is None:
                    return f"第 {i} 条为空"
            elif x is not None:
                return f"第 {i} 条类型不支持"
        return None
    return "译文必须是字符串或字符串数组"


def cmd_gate(args):
    blocking, warning = [], []

    def add(kind, **kw):
        (blocking if kind in BLOCKING_KINDS else warning).append(dict(type=kind, **kw))

    try:
        plan = load_plan(args.plan)
    except ValueError as e:
        add("漏译", why=str(e), count=0, paras=[])
        plan = {}

    mp = load_json(args.map).get("parts", {})

    # 用 --src 重算 map，交叉核对（防"plan 与文档错位后静默通过"）
    if args.src:
        kind = detect_kind(args.src)
        if kind is None:
            add("map 与源文档不符", why="--src 不是可识别的 docx/pptx")
        else:
            with zipfile.ZipFile(args.src) as zf:
                fresh = {p: {str(r["i"]): r["tsig"] for r in build_map(ET.fromstring(zf.read(p)), kind)[0]}
                         for p in part_list(zf, kind) if p in zf.namelist()}
            for part, rows in mp.items():
                for r in rows:
                    got = fresh.get(part, {}).get(str(r["i"]))
                    if got is not None and got != r.get("tsig"):
                        add("map 与源文档不符", part=part, paras=[str(r["i"])],
                            why="map 是旧版本生成的，请重跑 map")

    terms = []
    if args.terms:
        if not os.path.exists(args.terms):
            add("术语表不可用", why=f"术语表不存在：{args.terms}", paras=[])
        else:
            try:
                terms = read_terms(args.terms)
            except ValueError as e:
                add("术语表不可用", why=str(e), paras=[])

    translated = 0
    for part, rows in mp.items():
        src = {str(r["i"]): r for r in rows}
        p = {str(k): v for k, v in plan.get(part, {}).items()}
        translated += len(p)
        need = {i for i, r in src.items() if CJK.search(r["text"])}
        exempt = sorted(set(src) - need, key=int)
        if exempt:
            add("免译段落", part=part, count=len(exempt), paras=exempt[:10])
        badnum = [k for k in p if not k.lstrip("-").isdigit() or int(k) < 0]
        if badnum:
            add("越界或非整数编号", part=part, count=len(badnum), paras=badnum[:10])
        missing = sorted((need - set(p)) - set(badnum), key=int)
        if missing:
            add("漏译", part=part, count=len(missing), paras=missing[:20])
        hollow = []
        for k, v in p.items():
            err = plan_value_error(v, src.get(k, {}).get("runs"))
            if err:
                hollow.append(k)
            elif not plan_text(v).strip():
                hollow.append(k)
            elif k in src and plan_text(v).strip() == src[k]["text"].strip():
                hollow.append(k)
        if hollow:
            add("译文为空或同原文", part=part, count=len(hollow), paras=hollow[:20])
        unsafe = []
        for k in p:
            if k not in src:
                continue
            bs = src[k].get("blockers") or []
            hard = [b for b in bs if b != "mixed-format"]
            pv = p[k]
            if hard:
                unsafe.append(k)
                continue
            # 任何多 run 段落都必须给"条数正确的逐 run 译文"，否则就是把格式压平
            if src[k].get("runs", 1) > 1 and not (isinstance(pv, list) and len(pv) == src[k]["runs"]):
                unsafe.append(k)
                continue
            if isinstance(pv, list) and src[k].get("runs", 1) > 1:
                row_texts = src[k].get("run_texts") or []
                for i, item in enumerate(pv):
                    if not isinstance(item, dict):
                        continue
                    want, got = item.get("src"), (row_texts[i] if i < len(row_texts) else None)
                    if want is not None and got is not None and want != got:
                        add("逐 run 原文不符", part=part, paras=[k],
                            why=f"第 {i} 条 src 写「{want}」，原文是「{got}」")
                        break
                else:
                    # 纯字符串数组无法校验顺序 —— 只能靠人，给出提醒（不阻断）
                    if any(isinstance(x, str) for x in pv):
                        add("逐 run 顺序未校验", part=part, paras=[k],
                            why="建议用 [{\"src\":\"原文run文字\",\"out\":\"译文\"}] 形式，apply 会逐条核对顺序")
        if unsafe:
            add("不可自动回填", part=part, count=len(unsafe), paras=unsafe[:20],
                why="含 " + "/".join(sorted({b for k in unsafe for b in src[k]["blockers"]})))
        for term, trans, status in terms:
            if status not in STATUS_ENUM:
                add("待确认术语被翻译", term=term, status=status, paras=[],
                    why="状态不在枚举内（用户指定/已确认/待确认），按未确认处理")
                continue
            if status == "待确认":
                hit = [i for i, r in src.items() if term in r["text"] and i in p]
                if hit:
                    add("待确认术语被翻译", term=term, part=part, status=status, paras=hit[:10])
            elif trans:  # 已确认 / 用户指定：检查译文里真的用了这个译法
                miss = []
                for i, r in src.items():
                    if term not in r["text"] or i not in p:
                        continue
                    joined = plan_text(p[i])
                    if trans.lower() not in joined.lower():
                        miss.append(i)
                if miss:
                    add("译法不一致", term=term, part=part, paras=miss[:10],
                        why=f"术语表译法「{trans}」未出现在译文")

    for f in blocking + warning:
        rid, desc = RULES.get(f["type"], ("GATE-000", ""))
        f["rule_id"], f["rule_desc"] = rid, desc
        f["certainty"] = "deterministic"
        if f.get("paras"):
            f["evidence"] = [{"part": f.get("part"), "para": x,
                              "source_text": _snip(_src_text(mp, f.get("part"), x))}
                             for x in f["paras"][:3]]

    # reviewed 只列"这次真的跑了"的检查 —— 没做的必须进 checks_skipped，
    # 否则报告一边宣称"明写没查什么"，一边把没跑的规则列成已查（v0.5.0 的教训）
    ran = ["漏译", "越界或非整数编号", "免译段落", "译文为空或同原文", "不可自动回填"]
    if args.src:
        ran.append("map 与源文档不符")
    if args.terms:
        ran += ["待确认术语被翻译", "术语表不可用", "译法不一致"]
    skipped = []
    if not args.terms:
        skipped.append("术语检查未执行：没传 --terms，GATE-003/007/009 全部未跑")
    if not args.src:
        skipped.append("map 交叉核对未执行：没传 --src，GATE-006 未跑")

    report = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "gate": "blocked" if blocking else "pass",
        "tool": {"name": "translate_kit", "version": VERSION,
                 "src_sha256": _sha(args.src) if args.src and os.path.exists(args.src) else None,
                 "map_sha256": _sha(args.map), "plan_sha256": _sha(args.plan),
                 "terms_sha256": _sha(args.terms) if args.terms and os.path.exists(args.terms) else None},
        "reviewed": [f"{RULES[k][0]} {k}：{RULES[k][1]}" for k in ran if k in RULES],
        "checks_skipped": skipped,
        "not_verified": ["译义准确性：闸门只校验结构与值的存在性，不判断译文对不对",
                         "术语译法质量：只查状态枚举与译法是否出现，不评价译法优劣",
                         "回译校验：未做",
                         "内嵌对象内部文本：文本框内段落可被 map 到，但格式与位置未校验"],
        "paragraphs_planned": translated,
        "blocking": blocking,
        "warning": warning,
    }
    if args.out:
        _emit(report, args.out)
    print(f"GATE={report['gate']} blocking={len(blocking)} warning={len(warning)} planned={translated}")
    for b in blocking:
        print(f"  x [{b['rule_id']}] {b['type']}: {b.get('term','')} {b.get('why','')} "
              f"{b.get('paras','') if b.get('paras') else ''}")
    return 1 if (blocking and not args.warn_only) else 0


def _src_text(mp, part, idx):
    for r in mp.get(part, []):
        if str(r["i"]) == str(idx):
            return r.get("text", "")
    return ""


# ---------- CLI ----------

def main():
    ap = argparse.ArgumentParser(prog="translate_kit", description="文档翻译：map / apply / check / gate")
    ap.add_argument("--version", action="version", version=f"translate_kit {VERSION}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("map", help="抽段落结构：容器/格式指纹/阻断因素/原文指纹")
    m.add_argument("src", help="源 .docx / .pptx")
    m.add_argument("-o", "--out", help="输出 JSON 路径（不给就打印到屏幕）")
    m.set_defaults(f=cmd_map)

    a = sub.add_parser("apply", help="回填译文（只换文本，不重建 run）")
    a.add_argument("src", help="源文档")
    a.add_argument("plan", help="翻译计划 JSON：{'parts': {<part>: {'<段号>': '<译文>'}}}")
    a.add_argument("-o", "--out", required=True, help="产物路径（不能与源相同）")
    a.add_argument("--map", help="map 生成的 JSON：逐段比对原文指纹，防 plan 错位（强烈建议传）")
    a.add_argument("--terms", help="术语表路径，仅用于把它的 SHA-256 写进审计记录")
    a.add_argument("--gate", help="闸门报告 JSON：非 pass 则拒绝回填（推荐：gate→apply 串联）")
    a.add_argument("--force-unsafe", action="store_true",
                   help="强改含换行/超链接/修订/混排的段落（会破坏结构，默认拒绝）")
    a.set_defaults(f=cmd_apply)

    c = sub.add_parser("check", help="对比原文与译文：段数差/清空/收缩/膨胀/格式变化")
    c.add_argument("src", help="源文档")
    c.add_argument("dst", help="译文文档")
    c.add_argument("-o", "--out", help="报告 JSON 路径")
    c.set_defaults(f=cmd_check)

    g = sub.add_parser("gate", help="译前闸门：漏译/越界/空值/未确认术语/译法不一致/不可回填")
    g.add_argument("--map", required=True, help="map 生成的 JSON")
    g.add_argument("--plan", required=True, help="翻译计划 JSON")
    g.add_argument("--terms", help="术语表 TSV（必需列：源术语 / 译法 / 状态）")
    g.add_argument("--src", help="源文档；给了就重算 map 交叉核对，防旧 map")
    g.add_argument("-o", "--out", help="闸门报告 JSON 路径")
    g.add_argument("--warn-only", action="store_true", help="只告警不阻断（仅限内部草稿）")
    g.set_defaults(f=cmd_gate)

    args = ap.parse_args()
    sys.exit(args.f(args))


if __name__ == "__main__":
    main()
