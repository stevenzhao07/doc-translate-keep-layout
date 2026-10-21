#!/usr/bin/env python3
"""自测用：生成一份最小可用的 docx 样本（含加粗 run、编号、法规号），纯标准库。"""
import zipfile, sys, os

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

def para(*runs, bold_first=False):
    out = ['<w:p>']
    for j, t in enumerate(runs):
        rpr = '<w:rPr><w:b/></w:rPr>' if (bold_first and j == 0) else '<w:rPr><w:sz w:val="24"/></w:rPr>'
        out.append(f'<w:r>{rpr}<w:t xml:space="preserve">{t}</w:t></w:r>')
    out.append('</w:p>')
    return "".join(out)

DOC = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:body>
{para("1 范围", bold_first=True)}
{para("本文件规定了胫骨冲击锉手柄的清洁验证要求。")}
{para("适用于符合 MDR (EU) 2017/745 的 IIa 类器械。")}
{para("2 术语", bold_first=True)}
{para("2.1 清洁验证", "指通过检测残留物证明清洁工艺有效的过程。")}
{para("3 要求")}
{para("残留限度应不超过 10 μg/cm²，内毒素应低于 0.5 EU/mL。")}
</w:body>
</w:document>"""

def build(path):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CT)
        z.writestr("_rels/.rels", RELS)
        z.writestr("word/document.xml", DOC)
    print("built:", path)

if __name__ == "__main__":
    build(sys.argv[1] if len(sys.argv) > 1 else "sample.docx")
