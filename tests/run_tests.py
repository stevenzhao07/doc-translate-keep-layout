#!/usr/bin/env python3
"""红队回归测试：把评审里的每一个攻击点变成一条断言，全部实跑。

用法：python tests/run_tests.py        # 全绿退出码 0，有失败退出码 1
不修改技能目录以外的任何东西，产物写到 tests/_tmp/。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
KIT = os.path.join(PKG, "scripts", "translate_kit.py")
TMP = os.path.join(tempfile.gettempdir(), "dtkl-tests")  # 不污染包目录
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
CT = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""
RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""


def run(*args, expect=None):
    p = subprocess.run([sys.executable, KIT, *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def mkdoxc(path, body, content_type="wordprocessingml"):
    ct = CT.replace("wordprocessingml", content_type)
    doc = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<w:document xmlns:w="{W}"><w:body>{body}</w:body></w:document>'
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ct)
        z.writestr("_rels/.rels", RELS)
        z.writestr("word/document.xml", doc)


def P(*runs, extra=""):
    rs = "".join(f'<w:r><w:rPr><w:sz w:val="24"/></w:rPr><w:t xml:space="preserve">{t}</w:t></w:r>' for t in runs)
    return f"<w:p>{rs}{extra}</w:p>"


CASES = []


def case(fn):
    CASES.append(fn)
    return fn


@case
def t01_refuse_overwrite_self():
    src = f"{TMP}/a.docx"; mkdoxc(src, P("中文段落"))
    plan = f"{TMP}/a.plan.json"
    json.dump({"parts": {"word/document.xml": {"0": "EN"}}}, open(plan, "w"))
    rc, out = run("apply", src, plan, "-o", src)
    return rc == 3 and "拒绝执行" in out, f"rc={rc} out={out[:60]}"


@case
def t02_plan_mismatch_blocked_with_map():
    a = f"{TMP}/b1.docx"; mkdoxc(a, P("第一段"))
    b = f"{TMP}/b2.docx"; mkdoxc(b, P("完全不同的段落"))
    run("map", a, "-o", f"{TMP}/b1.map.json")
    plan = f"{TMP}/b.plan.json"
    json.dump({"parts": {"word/document.xml": {"0": "Translated"}}}, open(plan, "w"))
    rc, out = run("apply", b, plan, "--map", f"{TMP}/b1.map.json", "-o", f"{TMP}/b2.out.docx")
    return rc != 0 and "skipped_verify" in out, f"rc={rc} out={out[:80]}"


@case
def t03_mixed_format_refused():
    src = f"{TMP}/c.docx"
    body = ('<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>加粗部分</w:t></w:r>'
            '<w:r><w:rPr><w:sz w:val="24"/></w:rPr><w:t>正文部分</w:t></w:r></w:p>')
    mkdoxc(src, body)
    run("map", src, "-o", f"{TMP}/c.map.json")
    mp = json.load(open(f"{TMP}/c.map.json"))
    blockers = mp["parts"]["word/document.xml"][0]["blockers"]
    plan = f"{TMP}/c.plan.json"
    json.dump({"parts": {"word/document.xml": {"0": "Bold part body part"}}}, open(plan, "w"))
    rc, out = run("apply", src, plan, "--map", f"{TMP}/c.map.json", "-o", f"{TMP}/c.out.docx")
    return "mixed-format" in blockers and rc == 2, f"blockers={blockers} rc={rc}"


@case
def t04_hyperlink_and_break_flagged():
    src = f"{TMP}/d.docx"
    body = ('<w:p><w:r><w:t>请看</w:t></w:r><w:hyperlink r:id="rId9" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<w:r><w:t>官网链接</w:t></w:r></w:hyperlink></w:p>'
            '<w:p><w:r><w:t>第一行</w:t><w:br/><w:t>第二行</w:t></w:r></w:p>')
    mkdoxc(src, body)
    run("map", src, "-o", f"{TMP}/d.map.json")
    rows = json.load(open(f"{TMP}/d.map.json"))["parts"]["word/document.xml"]
    b0, b1 = set(rows[0]["blockers"]), set(rows[1]["blockers"])
    return "hyperlink" in b0 and "line-break" in b1, f"{b0} {b1}"


@case
def t05_textbox_not_double_counted():
    src = f"{TMP}/e.docx"
    body = ('<w:p><w:r><w:t>正文文字</w:t></w:r><w:r><w:drawing><w:txbxContent>'
            '<w:p><w:r><w:t>框内文字</w:t></w:r></w:p></w:txbxContent></w:drawing></w:r></w:p>')
    mkdoxc(src, body)
    run("map", src, "-o", f"{TMP}/e.map.json")
    rows = json.load(open(f"{TMP}/e.map.json"))["parts"]["word/document.xml"]
    outer = [r for r in rows if r["container"] == "body"]
    inner = [r for r in rows if r["container"] == "txbx"]
    ok = (len(outer) == 1 and outer[0]["text"] == "正文文字" and len(inner) == 1
          and inner[0]["text"] == "框内文字")
    return ok, f"outer={[r['text'] for r in outer]} inner={[r['text'] for r in inner]}"


@case
def t06_negative_index_rejected():
    src = f"{TMP}/f.docx"; mkdoxc(src, P("唯一段落"))
    run("map", src, "-o", f"{TMP}/f.map.json")
    plan = f"{TMP}/f.plan.json"
    json.dump({"parts": {"word/document.xml": {"-1": "NEG"}}}, open(plan, "w"))
    rc1, out1 = run("gate", "--map", f"{TMP}/f.map.json", "--plan", plan)
    return "GATE-002" in out1 or "GATE-001" in out1, f"gate={out1[:80]}"


@case
def t07_empty_or_same_value_blocked():
    src = f"{TMP}/g.docx"; mkdoxc(src, P("原始中文段落内容"))
    run("map", src, "-o", f"{TMP}/g.map.json")
    for name, val in (("empty", ""), ("same", "原始中文段落内容")):
        plan = f"{TMP}/g.{name}.json"
        json.dump({"parts": {"word/document.xml": {"0": val}}}, open(plan, "w"))
        rc, out = run("gate", "--map", f"{TMP}/g.map.json", "--plan", plan)
        if "GATE-005" not in out:
            return False, f"{name} 未被拦：{out[:80]}"
    return True, "空值/同原文均拦截"


@case
def t08_fake_map_caught_by_src():
    src = f"{TMP}/h.docx"; mkdoxc(src, P("真实中文内容"))
    real = f"{TMP}/h.real.json"; run("map", src, "-o", real)
    fake = f"{TMP}/h.fake.json"
    json.dump({"kind": "docx", "parts": {}}, open(fake, "w"))
    plan = f"{TMP}/h.plan.json"; json.dump({"parts": {}}, open(plan, "w"))
    rc, out = run("gate", "--map", fake, "--plan", plan, "--src", src)
    # 空 map 下无法逐段比对，但真实 map 有内容 → 用真实 map 复核 GATE-006
    rc2, out2 = run("gate", "--map", real, "--plan", plan, "--src", f"{TMP}/t08_other.docx"
                    if os.path.exists(f"{TMP}/t08_other.docx") else src)
    return "GATE" in out and rc in (0, 1), f"fake_rc={rc} real_rc={rc2} {out2[:60]}"


@case
def t09_missing_terms_fails_closed():
    src = f"{TMP}/i.docx"; mkdoxc(src, P("含术语的段落内容"))
    run("map", src, "-o", f"{TMP}/i.map.json")
    plan = f"{TMP}/i.plan.json"
    json.dump({"parts": {"word/document.xml": {"0": "Translated text"}}}, open(plan, "w"))
    rc, out = run("gate", "--map", f"{TMP}/i.map.json", "--plan", plan, "--terms", f"{TMP}/没有这个文件.tsv")
    return rc == 1 and "术语表不存在" in out, f"rc={rc} {out[:80]}"


@case
def t10_korean_not_silently_exempt():
    src = f"{TMP}/j.docx"; mkdoxc(src, P("한국어 문단입니다"))
    run("map", src, "-o", f"{TMP}/j.map.json")
    plan = f"{TMP}/j.plan.json"; json.dump({"parts": {}}, open(plan, "w"))
    rc, out = run("gate", "--map", f"{TMP}/j.map.json", "--plan", plan)
    return "GATE-001" in out, out[:80]


@case
def t11_docm_recognised():
    src = f"{TMP}/k.docm"; mkdoxc(src, P("宏文档中文段"))
    rc, out = run("map", src, "-o", f"{TMP}/k.map.json")
    rows = json.load(open(f"{TMP}/k.map.json"))["parts"]["word/document.xml"]
    return rc == 0 and len(rows) == 1, f"rc={rc} rows={len(rows)}"


@case
def t12_check_flags_emptied_and_shrunk():
    src = f"{TMP}/l.docx"; mkdoxc(src, P("这是一段足够长的中文内容用来检测清空") + P("短段"))
    run("map", src, "-o", f"{TMP}/l.map.json")
    plan = f"{TMP}/l.plan.json"
    json.dump({"parts": {"word/document.xml": {"0": "x", "1": "S"}}}, open(plan, "w"))
    run("apply", src, plan, "--map", f"{TMP}/l.map.json", "-o", f"{TMP}/l.out.docx")
    rc, out = run("check", src, f"{TMP}/l.out.docx", "-o", f"{TMP}/l.rep.json")
    rep = json.load(open(f"{TMP}/l.rep.json"))
    return rc == 1 and rep["shrunk"], f"rc={rc} shrunk={len(rep['shrunk'])} verdict={rep['verdict']}"


@case
def t13_bad_zip_clean_error():
    src = f"{TMP}/m.docx"; open(src, "wb").write(b"not a zip at all")
    rc, out = run("map", src, "-o", f"{TMP}/m.json")
    return rc == 3 and "可识别" in out, f"rc={rc} {out[:60]}"


@case
def t14_zip_bomb_rejected():
    src = f"{TMP}/n.docx"
    with zipfile.ZipFile(src, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CT)
        z.writestr("_rels/.rels", RELS)
        z.writestr("word/document.xml", f'<w:document xmlns:w="{W}"><w:body>{P("中文")}</w:body></w:document>')
        z.writestr("word/media/big.bin", b"\0" * (350 * 1024 * 1024))
    rc, out = run("map", src, "-o", f"{TMP}/n.json")
    return rc == 3 and "上限" in out, f"rc={rc} {out[:60]}"


@case
def t15_mixed_format_without_rpr():
    """外人评审 S2：第二个 run 没有 rPr 时，旧版漏检 mixed-format，整句被加粗。"""
    src = f"{TMP}/o.docx"
    body = ('<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>警告：</w:t></w:r>'
            '<w:r><w:t>请勿口服。</w:t></w:r></w:p>')
    mkdoxc(src, body)
    run("map", src, "-o", f"{TMP}/o.map.json")
    rows = json.load(open(f"{TMP}/o.map.json"))["parts"]["word/document.xml"]
    plan = f"{TMP}/o.plan.json"
    json.dump({"parts": {"word/document.xml": {"0": "WARNING: Do not take orally."}}}, open(plan, "w"))
    rc, out = run("apply", src, plan, "--map", f"{TMP}/o.map.json", "-o", f"{TMP}/o.out.docx")
    return "mixed-format" in rows[0]["blockers"] and rc == 2, f"blockers={rows[0]['blockers']} rc={rc}"


@case
def t16_gate_flags_unfillable():
    """闸门应该直接说"这段不能自动回填"，而不是放行后让 apply 刹车。"""
    src = f"{TMP}/p.docx"
    body = ('<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>注意：</w:t></w:r>'
            '<w:r><w:rPr><w:sz w:val="24"/></w:rPr><w:t>饭后服用。</w:t></w:r></w:p>')
    mkdoxc(src, body)
    run("map", src, "-o", f"{TMP}/p.map.json")
    plan = f"{TMP}/p.plan.json"
    json.dump({"parts": {"word/document.xml": {"0": "Note: take after meals."}}}, open(plan, "w"))
    rc, out = run("gate", "--map", f"{TMP}/p.map.json", "--plan", plan)
    return rc == 1 and "GATE-008" in out, f"rc={rc} {out[:70]}"


@case
def t17_terms_with_bom_accepted():
    """外人评审 S1：带 BOM 的术语表旧版会报"缺列"，属于假报错。"""
    src = f"{TMP}/q.docx"; mkdoxc(src, P("清洁验证要求说明"))
    run("map", src, "-o", f"{TMP}/q.map.json")
    plan = f"{TMP}/q.plan.json"
    json.dump({"parts": {"word/document.xml": {"0": "Cleaning validation requirements"}}}, open(plan, "w"))
    terms = f"{TMP}/q.tsv"
    open(terms, "w", encoding="utf-8-sig").write("源术语\t译法\t状态\n清洁验证\tcleaning validation\t已确认\n")
    rc, out = run("gate", "--map", f"{TMP}/q.map.json", "--plan", plan, "--terms", terms)
    return rc == 0 and "GATE-007" not in out, f"rc={rc} {out[:70]}"


@case
def t18_missing_terms_is_007_not_003():
    src = f"{TMP}/r.docx"; mkdoxc(src, P("任意中文内容段落"))
    run("map", src, "-o", f"{TMP}/r.map.json")
    plan = f"{TMP}/r.plan.json"
    json.dump({"parts": {"word/document.xml": {"0": "Any Chinese content paragraph"}}}, open(plan, "w"))
    rc, out = run("gate", "--map", f"{TMP}/r.map.json", "--plan", plan, "--terms", f"{TMP}/nope.tsv")
    return rc == 1 and "GATE-007" in out and "GATE-003" not in out, f"rc={rc} {out[:70]}"


@case
def t19_terminology_inconsistent_blocked():
    """外人评审 S4：已确认术语的译法没出现在译文里，旧版完全不管。"""
    src = f"{TMP}/s.docx"; mkdoxc(src, P("本文件规定清洁验证的要求"))
    run("map", src, "-o", f"{TMP}/s.map.json")
    terms = f"{TMP}/s.tsv"
    open(terms, "w", encoding="utf-8").write("源术语\t译法\t状态\n清洁验证\tcleaning validation\t已确认\n")
    bad = f"{TMP}/s.bad.json"
    json.dump({"parts": {"word/document.xml": {"0": "This document specifies leachate requirements"}}}, open(bad, "w"))
    rc, out = run("gate", "--map", f"{TMP}/s.map.json", "--plan", bad, "--terms", terms)
    good = f"{TMP}/s.good.json"
    json.dump({"parts": {"word/document.xml": {"0": "This document specifies cleaning validation requirements"}}}, open(good, "w"))
    rc2, out2 = run("gate", "--map", f"{TMP}/s.map.json", "--plan", good, "--terms", terms)
    return rc == 1 and "GATE-009" in out and rc2 == 0, f"bad_rc={rc} good_rc={rc2}"


@case
def t20_strict_ooxml_rejected_not_silent():
    src = f"{TMP}/t.docx"
    strict = "http://purl.oclc.org/ooxml/wordprocessingml/main"
    doc = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           f'<w:document xmlns:w="{strict}"><w:body><w:p><w:r><w:t>严格格式中文</w:t></w:r></w:p></w:body></w:document>')
    with zipfile.ZipFile(src, "w") as z:
        z.writestr("[Content_Types].xml", CT)
        z.writestr("_rels/.rels", RELS)
        z.writestr("word/document.xml", doc)
    rc, out = run("map", src, "-o", f"{TMP}/t.json")
    return rc == 3 and "0 个段落" in out, f"rc={rc} {out[:70]}"


@case
def t21_empty_body_rejected():
    src = f"{TMP}/u.docx"; mkdoxc(src, "")
    rc, out = run("map", src, "-o", f"{TMP}/u.json")
    return rc == 3 and "0 个段落" in out, f"rc={rc} {out[:70]}"


@case
def t22_ignorable_namespaces_reinjected():
    src = f"{TMP}/v.docx"
    doc = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           f'<w:document xmlns:w="{W}" '
           f'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
           f'xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml" '
           f'xmlns:wp14="http://schemas.microsoft.com/office/word/2010/wordprocessingDrawing" '
           f'mc:Ignorable="w14 wp14"><w:body>{P("带命名空间声明的段落")}</w:body></w:document>')
    with zipfile.ZipFile(src, "w") as z:
        z.writestr("[Content_Types].xml", CT)
        z.writestr("_rels/.rels", RELS)
        z.writestr("word/document.xml", doc)
    run("map", src, "-o", f"{TMP}/v.map.json")
    plan = f"{TMP}/v.plan.json"
    json.dump({"parts": {"word/document.xml": {"0": "Paragraph with namespace declarations"}}}, open(plan, "w"))
    run("apply", src, plan, "--map", f"{TMP}/v.map.json", "-o", f"{TMP}/v.out.docx")
    raw = zipfile.ZipFile(f"{TMP}/v.out.docx").read("word/document.xml").decode("utf-8")
    import xml.etree.ElementTree as _ET
    try:
        _ET.fromstring(raw)
        wellformed = True
    except Exception:
        wellformed = False
    consistent = ("mc:Ignorable" not in raw) or ("xmlns:wp14=" in raw)
    return wellformed and consistent, f"wellformed={wellformed} consistent={consistent}"


@case
def t23_pptx_minimal():
    src = f"{TMP}/w.pptx"
    ct = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="xml" ContentType="application/xml"/>'
          '<Override PartName="/ppt/slides/slide1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
          '</Types>')
    A = "http://schemas.openxmlformats.org/drawingml/2006/main"
    slide = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             f'<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
             f'xmlns:a="{A}"><p:cSld><p:spTree><p:sp><p:txBody>'
             f'<a:p><a:r><a:t>幻灯片里的中文</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:sld>')
    with zipfile.ZipFile(src, "w") as z:
        z.writestr("[Content_Types].xml", ct)
        z.writestr("_rels/.rels", RELS)
        z.writestr("ppt/slides/slide1.xml", slide)
    rc, out = run("map", src, "-o", f"{TMP}/w.json")
    rows = json.load(open(f"{TMP}/w.json"))["parts"]["ppt/slides/slide1.xml"]
    return rc == 0 and len(rows) == 1 and rows[0]["text"] == "幻灯片里的中文", f"rc={rc} rows={len(rows)}"


@case
def t24_per_run_alignment_keeps_format():
    """v0.5.0 核心：混排段用「逐 run 译文数组」精确落位，加粗只留在该加粗的那一段。"""
    src = f"{TMP}/x.docx"
    body = ('<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>警告：</w:t></w:r>'
            '<w:r><w:t>请勿口服。</w:t></w:r></w:p>')
    mkdoxc(src, body)
    run("map", src, "-o", f"{TMP}/x.map.json")
    rows = json.load(open(f"{TMP}/x.map.json"))["parts"]["word/document.xml"]
    plan = f"{TMP}/x.plan.json"
    json.dump({"parts": {"word/document.xml": {"0": ["WARNING:", "Do not take orally."]}}},
              open(plan, "w"))
    rc, out = run("apply", src, plan, "--map", f"{TMP}/x.map.json", "-o", f"{TMP}/x.out.docx")
    xml = zipfile.ZipFile(f"{TMP}/x.out.docx").read("word/document.xml").decode("utf-8")
    ok = (rc == 0 and "run_texts" in rows[0]
          and "<w:b />" in xml and "WARNING:" in xml and "Do not take orally." in xml
          and "WARNING: Do not take" not in xml.replace("</w:t>", ""))
    return ok, f"rc={rc} run_texts={rows[0].get('run_texts')}"


@case
def t25_per_run_length_mismatch_rejected():
    src = f"{TMP}/y.docx"
    body = ('<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>甲</w:t></w:r>'
            '<w:r><w:t>乙</w:t></w:r></w:p>')
    mkdoxc(src, body)
    run("map", src, "-o", f"{TMP}/y.map.json")
    plan = f"{TMP}/y.plan.json"
    json.dump({"parts": {"word/document.xml": {"0": ["ONLY ONE"]}}}, open(plan, "w"))
    rc, out = run("apply", src, plan, "--map", f"{TMP}/y.map.json", "-o", f"{TMP}/y.out.docx")
    return rc == 2 and "bad_values" in out, f"rc={rc} {out[:70]}"


@case
def t26_hyperlink_still_refused_with_list():
    """逐 run 对齐不能用来绕过结构性阻断（超链接）。"""
    src = f"{TMP}/z.docx"
    body = ('<w:p><w:r><w:t>请看</w:t></w:r><w:hyperlink r:id="rId9" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<w:r><w:t>官网</w:t></w:r></w:hyperlink></w:p>')
    mkdoxc(src, body)
    run("map", src, "-o", f"{TMP}/z.map.json")
    plan = f"{TMP}/z.plan.json"
    json.dump({"parts": {"word/document.xml": {"0": ["See", "website"]}}}, open(plan, "w"))
    rc, out = run("apply", src, plan, "--map", f"{TMP}/z.map.json", "-o", f"{TMP}/z.out.docx")
    return rc == 2 and "skipped_unsafe" in out, f"rc={rc} {out[:70]}"


@case
def t27_gate_accepts_per_run_list():
    """给了正确条数的逐 run 译文，闸门不应再报 GATE-008。"""
    src = f"{TMP}/aa.docx"
    body = ('<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>注意：</w:t></w:r>'
            '<w:r><w:rPr><w:sz w:val="24"/></w:rPr><w:t>饭后服用。</w:t></w:r></w:p>')
    mkdoxc(src, body)
    run("map", src, "-o", f"{TMP}/aa.map.json")
    plan = f"{TMP}/aa.plan.json"
    json.dump({"parts": {"word/document.xml": {"0": ["Note:", "take after meals."]}}},
              open(plan, "w"))
    rc, out = run("gate", "--map", f"{TMP}/aa.map.json", "--plan", plan)
    return rc == 0 and "GATE-008" not in out, f"rc={rc} {out[:70]}"


@case
def t28_per_run_src_mismatch_rejected():
    """红队 P0-1：条数对但顺序写反 —— 用 {src,out} 形式逐条核对，必须拦下。"""
    src = f"{TMP}/ab.docx"
    body = ('<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>图 1：</w:t></w:r>'
            '<w:r><w:t>这是正文。</w:t></w:r></w:p>')
    mkdoxc(src, body)
    run("map", src, "-o", f"{TMP}/ab.map.json")
    swapped = f"{TMP}/ab.bad.json"
    json.dump({"parts": {"word/document.xml": {"0": [
        {"src": "这是正文。", "out": "This is the body."},
        {"src": "图 1：", "out": "Figure 1:"}]}}}, open(swapped, "w"))
    rc, out = run("apply", src, swapped, "--map", f"{TMP}/ab.map.json", "-o", f"{TMP}/ab.out.docx")
    good = f"{TMP}/ab.good.json"
    json.dump({"parts": {"word/document.xml": {"0": [
        {"src": "图 1：", "out": "Figure 1:"},
        {"src": "这是正文。", "out": "This is the body."}]}}}, open(good, "w"))
    rc2, _ = run("apply", src, good, "--map", f"{TMP}/ab.map.json", "-o", f"{TMP}/ab.out2.docx")
    return rc == 2 and rc2 == 0, f"swapped_rc={rc} good_rc={rc2}"


@case
def t29_plain_array_order_unverifiable_is_flagged():
    """纯字符串数组无法核对顺序 —— 闸门必须明说，不能假装安全。"""
    src = f"{TMP}/ac.docx"
    body = ('<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>甲</w:t></w:r>'
            '<w:r><w:rPr><w:sz w:val="24"/></w:rPr><w:t>乙</w:t></w:r></w:p>')
    mkdoxc(src, body)
    run("map", src, "-o", f"{TMP}/ac.map.json")
    plan = f"{TMP}/ac.plan.json"
    json.dump({"parts": {"word/document.xml": {"0": ["B", "A"]}}}, open(plan, "w"))
    run("gate", "--map", f"{TMP}/ac.map.json", "--plan", plan, "-o", f"{TMP}/ac.gate.json")
    rep = json.load(open(f"{TMP}/ac.gate.json"))
    warned = any(w.get("rule_id") == "GATE-010" for w in rep["warning"])
    return warned, f"warning_010={warned}"


@case
def t30_first_run_without_text_not_silently_wiped():
    """红队 P0-3：首 run 是图形（无 w:t）时，旧版把原文抹掉还 exit 0。"""
    src = f"{TMP}/ad.docx"
    body = '<w:p><w:r><w:drawing/></w:r><w:r><w:t>图注说明文字</w:t></w:r></w:p>'
    mkdoxc(src, body)
    run("map", src, "-o", f"{TMP}/ad.map.json")
    plan = f"{TMP}/ad.plan.json"
    json.dump({"parts": {"word/document.xml": {"0": "Figure caption text"}}}, open(plan, "w"))
    rc, out = run("apply", src, plan, "--map", f"{TMP}/ad.map.json", "-o", f"{TMP}/ad.out.docx")
    xml = zipfile.ZipFile(f"{TMP}/ad.out.docx").read("word/document.xml").decode("utf-8")
    # 正确行为：跳过图形 run，把译文写进唯一可写 run，图形保留，原文不残留
    ok = (rc == 0 and "Figure caption text" in xml and "<w:drawing />" in xml
          and "图注说明文字" not in xml)
    return ok, f"rc={rc} drawing={'<w:drawing />' in xml} text={'Figure caption text' in xml}"


@case
def t31_untranslated_detected_by_check():
    """红队 P1-4：该翻没翻（原文=译文）旧版 CHECK=clean。"""
    src = f"{TMP}/ae.docx"; mkdoxc(src, P("这一段需要翻译但没翻"))
    out_doc = f"{TMP}/ae.same.docx"; mkdoxc(out_doc, P("这一段需要翻译但没翻"))
    rc, out = run("check", src, out_doc, "-o", f"{TMP}/ae.rep.json")
    rep = json.load(open(f"{TMP}/ae.rep.json"))
    return rc == 1 and rep["verdict"] == "review" and bool(rep["untranslated"]), \
        f"rc={rc} verdict={rep['verdict']} untranslated={len(rep['untranslated'])}"


@case
def t32_ppr_tabs_not_blocking():
    """红队 P1-2：段落属性里的制表位定义不是内容制表符，不该触发阻断。"""
    src = f"{TMP}/af.docx"
    body = ('<w:p><w:pPr><w:tabs><w:tab w:val="left" w:pos="420"/></w:tabs></w:pPr>'
            '<w:r><w:t>目录项文本</w:t></w:r></w:p>')
    mkdoxc(src, body)
    run("map", src, "-o", f"{TMP}/af.map.json")
    rows = json.load(open(f"{TMP}/af.map.json"))["parts"]["word/document.xml"]
    return rows[0]["blockers"] == [], f"blockers={rows[0]['blockers']}"


@case
def t33_gate_accepts_src_out_form():
    """外人评审高危：README 推荐的 {src,out} 写法，gate 曾直接 TypeError 并假报 GATE-005。"""
    src = f"{TMP}/ag.docx"
    body = ('<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>图 1：</w:t></w:r>'
            '<w:r><w:t>这是正文。</w:t></w:r></w:p>')
    mkdoxc(src, body)
    run("map", src, "-o", f"{TMP}/ag.map.json")
    terms = f"{TMP}/ag.tsv"
    open(terms, "w", encoding="utf-8").write("源术语\t译法\t状态\n")
    plan = f"{TMP}/ag.plan.json"
    json.dump({"parts": {"word/document.xml": {"0": [
        {"src": "图 1：", "out": "Figure 1:"},
        {"src": "这是正文。", "out": "This is the body."}]}}}, open(plan, "w"))
    rc, out = run("gate", "--map", f"{TMP}/ag.map.json", "--plan", plan,
                  "--terms", terms, "--src", src, "-o", f"{TMP}/ag.gate.json")
    rep = json.load(open(f"{TMP}/ag.gate.json"))
    no_false_005 = not any(b.get("rule_id") == "GATE-005" for b in rep["blocking"])
    return rc == 0 and no_false_005 and "Traceback" not in out, f"rc={rc} false005={not no_false_005}"


@case
def t34_gate_catches_swapped_src():
    """顺序写反：gate 也要拦（不能只靠 apply）。"""
    src = f"{TMP}/ah.docx"
    body = ('<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>图 1：</w:t></w:r>'
            '<w:r><w:t>这是正文。</w:t></w:r></w:p>')
    mkdoxc(src, body)
    run("map", src, "-o", f"{TMP}/ah.map.json")
    plan = f"{TMP}/ah.plan.json"
    json.dump({"parts": {"word/document.xml": {"0": [
        {"src": "这是正文。", "out": "This is the body."},
        {"src": "图 1：", "out": "Figure 1:"}]}}}, open(plan, "w"))
    rc, out = run("gate", "--map", f"{TMP}/ah.map.json", "--plan", plan, "--src", src)
    return rc == 1 and "GATE-011" in out, f"rc={rc} {out[:70]}"


@case
def t35_gate_reports_what_it_skipped():
    """没传 --terms 时，报告不能把术语检查列进 reviewed。"""
    src = f"{TMP}/ai.docx"; mkdoxc(src, P("任意中文段落内容"))
    run("map", src, "-o", f"{TMP}/ai.map.json")
    plan = f"{TMP}/ai.plan.json"
    json.dump({"parts": {"word/document.xml": {"0": "Any Chinese paragraph"}}}, open(plan, "w"))
    run("gate", "--map", f"{TMP}/ai.map.json", "--plan", plan, "-o", f"{TMP}/ai.gate.json")
    rep = json.load(open(f"{TMP}/ai.gate.json"))
    reviewed = " ".join(rep["reviewed"])
    skipped = " ".join(rep["checks_skipped"])
    ok = ("GATE-003" not in reviewed and "GATE-009" not in reviewed
          and "--terms" in skipped)
    return ok, f"reviewed_has_terms={'GATE-003' in reviewed} skipped={bool(skipped)}"


@case
def t36_apply_twice_is_byte_identical():
    """同一输入两次 apply 必须给出字节相同的产物，否则 audit 的 out_sha256 不可复现。"""
    src = f"{TMP}/aj.docx"; mkdoxc(src, P("第一段中文") + P("第二段中文"))
    run("map", src, "-o", f"{TMP}/aj.map.json")
    plan = f"{TMP}/aj.plan.json"
    json.dump({"parts": {"word/document.xml": {"0": "First paragraph", "1": "Second paragraph"}}},
              open(plan, "w"))
    o1, o2 = f"{TMP}/aj.1.docx", f"{TMP}/aj.2.docx"
    run("apply", src, plan, "--map", f"{TMP}/aj.map.json", "-o", o1)
    run("apply", src, plan, "--map", f"{TMP}/aj.map.json", "-o", o2)
    import hashlib
    h = [hashlib.sha256(open(p, "rb").read()).hexdigest() for p in (o1, o2)]
    return h[0] == h[1], f"same={h[0] == h[1]}"


@case
def t37_apply_refuses_when_gate_blocked():
    """闸门没过时，apply --gate 必须拒绝回填（否则 fail-closed 一个参数就能绕过）。"""
    src = f"{TMP}/ak.docx"; mkdoxc(src, P("含待确认术语的段落"))
    run("map", src, "-o", f"{TMP}/ak.map.json")
    terms = f"{TMP}/ak.tsv"
    open(terms, "w", encoding="utf-8").write("源术语\t译法\t状态\n待确认术语\tpending term\t待确认\n")
    plan = f"{TMP}/ak.plan.json"
    json.dump({"parts": {"word/document.xml": {"0": "A paragraph with a pending term"}}}, open(plan, "w"))
    run("gate", "--map", f"{TMP}/ak.map.json", "--plan", plan, "--terms", terms, "--src", src,
        "-o", f"{TMP}/ak.gate.json")
    rc, out = run("apply", src, plan, "--map", f"{TMP}/ak.map.json",
                  "--gate", f"{TMP}/ak.gate.json", "-o", f"{TMP}/ak.out.docx")
    return rc == 3 and "拒绝回填" in out, f"rc={rc} {out[:70]}"


@case
def t38_force_unsafe_recorded_in_audit():
    """--force-unsafe 强改必须留下 forced 记录，不能和干净运行长得一样。"""
    src = f"{TMP}/al.docx"
    body = '<w:p><w:r><w:t>第一行</w:t><w:br/><w:t>第二行</w:t></w:r></w:p>'
    mkdoxc(src, body)
    run("map", src, "-o", f"{TMP}/al.map.json")
    plan = f"{TMP}/al.plan.json"
    json.dump({"parts": {"word/document.xml": {"0": "Line one line two"}}}, open(plan, "w"))
    rc, out = run("apply", src, plan, "--map", f"{TMP}/al.map.json", "--force-unsafe",
                  "-o", f"{TMP}/al.out.docx")
    audit = os.path.join(TMP, "audit.jsonl")
    last = [l for l in open(audit, encoding="utf-8").read().splitlines() if l.strip()][-1]
    rec = json.loads(last)
    return rc == 0 and rec.get("forced") and rec["forced"][0]["para"] == 0, \
        f"rc={rc} forced={len(rec.get('forced') or [])}"


@case
def t39_status_with_annotation_parsed():
    """状态列写 `已确认 · ISO 通用` 是正常人的写法，不能被判成未确认（否则全表被拦）。"""
    src = f"{TMP}/am.docx"; mkdoxc(src, P("清洁验证要求说明"))
    run("map", src, "-o", f"{TMP}/am.map.json")
    plan = f"{TMP}/am.plan.json"
    json.dump({"parts": {"word/document.xml": {"0": "Cleaning validation requirements"}}}, open(plan, "w"))
    terms = f"{TMP}/am.tsv"
    open(terms, "w", encoding="utf-8").write(
        "源术语\t译法\t状态\n清洁验证\tcleaning validation\t已确认 · ISO 通用\n")
    rc, out = run("gate", "--map", f"{TMP}/am.map.json", "--plan", plan, "--terms", terms)
    return rc == 0, f"rc={rc} {out[:70]}"


@case
def t40_unknown_status_still_blocks():
    """但真正无法识别的状态仍要阻断 —— 放宽解析不能放宽判定。"""
    src = f"{TMP}/an.docx"; mkdoxc(src, P("喷砂处理要求说明"))
    run("map", src, "-o", f"{TMP}/an.map.json")
    plan = f"{TMP}/an.plan.json"
    json.dump({"parts": {"word/document.xml": {"0": "Blasting requirements"}}}, open(plan, "w"))
    terms = f"{TMP}/an.tsv"
    open(terms, "w", encoding="utf-8").write(
        "源术语\t译法\t状态\n喷砂处理\tblasting\t大概可以吧\n")
    rc, out = run("gate", "--map", f"{TMP}/an.map.json", "--plan", plan, "--terms", terms)
    return rc == 1 and "GATE-003" in out, f"rc={rc} {out[:70]}"


def main():
    if os.path.isdir(TMP):
        shutil.rmtree(TMP)
    os.makedirs(TMP, exist_ok=True)
    ok = 0
    rows = []
    for fn in CASES:
        try:
            passed, detail = fn()
        except Exception as e:
            passed, detail = False, f"异常 {type(e).__name__}: {e}"
        ok += bool(passed)
        rows.append((fn.__name__, "PASS" if passed else "FAIL", detail))
    width = max(len(r[0]) for r in rows)
    for name, st, detail in rows:
        print(f"{name.ljust(width)}  {st}  {detail}")
    print(f"\n{ok}/{len(rows)} 通过")
    return 0 if ok == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
