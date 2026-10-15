#!/usr/bin/env python3
"""Word(.docx) · PowerPoint(.pptx) · Excel(.xlsx) 워터마크 제거.

문서 안의 워터마크 '개체'만 빼낸다. 본문은 그대로 편집 가능한 상태로 남는다.

자동으로 찾는 것
  docx  Word '워터마크' 기능으로 넣은 글자/그림, 머리글의 WordArt, 그림 배경
  pptx  이름에 Watermark 가 들어간 도형
  xlsx  시트 배경 그림, 머리글/바닥글 그림(&G)
직접 지정
  --text 문구          그 문구로 된 도형·글상자·머리글/바닥글 글자를 지움 (여러 번 가능)
  --behind-images      (docx) 머리글에 '텍스트 뒤'로 깔린 그림도 지움

.doc .ppt .xls .rtf .odt .odp .ods .hwp 는 LibreOffice(soffice)가 있으면
docx/pptx/xlsx 로 바꾼 뒤 처리한다 (결과도 바뀐 형식으로 저장).

예시
  python remove_office_watermark.py report.docx --list
  python remove_office_watermark.py report.docx --text "대외비"
  python remove_office_watermark.py deck.pptx --text DRAFT
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from collections import Counter
from pathlib import Path

try:
    from lxml import etree
except ImportError:  # pragma: no cover
    sys.exit("필요한 패키지가 없습니다: pip install lxml")

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "v": "urn:schemas-microsoft-com:vml",
    "o": "urn:schemas-microsoft-com:office:office",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "xdr": "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing",
}
WM_WORDS = ("watermark", "워터마크")
CONVERT = {".doc": "docx", ".dot": "docx", ".rtf": "docx", ".odt": "docx", ".hwp": "docx",
           ".ppt": "pptx", ".odp": "pptx", ".xls": "xlsx", ".ods": "xlsx"}
KINDS = {".docx": "docx", ".docm": "docx", ".dotx": "docx", ".dotm": "docx",
         ".pptx": "pptx", ".pptm": "pptx", ".potx": "pptx", ".xlsx": "xlsx", ".xlsm": "xlsx", ".xltx": "xlsx"}


def q(tag: str) -> str:
    prefix, local = tag.split(":")
    return f"{{{NS[prefix]}}}{local}"


def norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "").lower()


def is_wm_name(s) -> bool:
    s = str(s or "").lower()
    return any(w in s for w in WM_WORDS)


class Rules:
    def __init__(self, patterns, behind_images):
        self.patterns = [norm(p) for p in patterns if norm(p)]
        self.raw = [p for p in patterns if norm(p)]
        self.behind_images = behind_images

    def only_pattern(self, text: str) -> bool:
        t = norm(text)
        return bool(t) and any(t.replace(p, "") == "" for p in self.patterns)

    def regex(self):
        if not self.raw:
            return None
        alts = [r"\s*".join(re.escape(ch) for ch in re.sub(r"\s+", "", p)) for p in self.raw]
        return re.compile("|".join(alts), re.I)


def all_text(el) -> str:
    parts = [t.text or "" for t in el.iter(q("w:t"), q("a:t"), q("x:t"))]
    parts += [tp.get("string", "") for tp in el.iter(q("v:textpath"))]
    return "".join(parts)


def shape_names(el) -> list[str]:
    names = []
    for e in el.iter():
        for k in ("id", q("o:spid"), "name", "descr", "title", "alt"):
            if e.get(k):
                names.append(e.get(k))
    return names


def drop(el):
    parent = el.getparent()
    if parent is not None:
        parent.remove(el)


# ---------------------------------------------------------------- docx

CONTAINERS = {q("mc:AlternateContent"), q("w:pict"), q("w:drawing"), q("w:object")}


def docx_part(root, part: str, rules: Rules, log: list):
    is_hf = "/header" in part or "/footer" in part
    changed = False

    tops = []
    for el in root.iter(q("w:pict"), q("w:drawing"), q("w:object")):
        top = el
        while top.getparent() is not None and top.getparent().tag in CONTAINERS:
            top = top.getparent()
        if top not in tops:
            tops.append(top)

    for top in tops:
        if top.getparent() is None:
            continue
        names = shape_names(top)
        text = all_text(top)
        has_textpath = any(True for _ in top.iter(q("v:textpath")))
        has_image = any(True for _ in top.iter(q("v:imagedata"), q("a:blip")))
        behind = any(a.get("behindDoc") == "1" for a in top.iter(q("wp:anchor"))) or \
            any("z-index:-" in (s.get("style") or "") for s in top.iter())
        reason = None
        if any(is_wm_name(n) for n in names):
            reason = "Word 워터마크"
        elif is_hf and has_textpath:
            reason = "머리글의 WordArt 글자"
        elif rules.patterns and rules.only_pattern(text):
            reason = "지정 문구 도형/글상자"
        elif rules.behind_images and is_hf and behind and has_image and not norm(text):
            reason = "머리글의 텍스트 뒤 그림"
        if reason:
            desc = f" '{text.strip()[:40]}'" if norm(text) else (" (그림)" if has_image else "")
            log.append(f"{part}: {reason}{desc} 제거")
            run = top.getparent()
            drop(top)
            if run is not None and run.tag == q("w:r") and all(c.tag == q("w:rPr") for c in run):
                drop(run)
            changed = True

    # 머리글/바닥글의 일반 글자
    rx = rules.regex()
    if is_hf and rx:
        for para in root.iter(q("w:p")):
            ts = [t for t in para.iter(q("w:t")) if not any(a.tag in CONTAINERS for a in t.iterancestors())]
            ptext = "".join(t.text or "" for t in ts)
            if not rx.search(ptext):
                continue
            if rules.only_pattern(ptext):
                for t in ts:
                    t.text = ""
            else:
                for t in ts:
                    if t.text and rx.search(t.text):
                        t.text = rx.sub("", t.text)
            log.append(f"{part}: 머리글/바닥글 문구 '{ptext.strip()[:40]}' 제거")
            changed = True

    # 그림 배경
    if part.endswith("document.xml"):
        for bg in root.findall(q("w:background")):
            if any(e.get(q("r:id")) or e.get(q("o:relid")) for e in bg.iter()):
                log.append(f"{part}: 페이지 배경 그림 제거")
                drop(bg)
                changed = True
    return changed


def docx_list(root, part, found: list):
    if not ("/header" in part or "/footer" in part):
        return
    for el in root.iter(q("w:pict"), q("w:drawing")):
        t = all_text(el).strip()
        n = [x for x in shape_names(el) if not x.startswith("_x0000")][:2]
        img = any(True for _ in el.iter(q("v:imagedata"), q("a:blip")))
        found.append(f"{part}: 도형 {n} 글자={t[:40]!r}{' 그림 포함' if img else ''}")
    for para in root.iter(q("w:p")):
        t = "".join(x.text or "" for x in para.iter(q("w:t"))).strip()
        if t:
            found.append(f"{part}: 글자 {t[:60]!r}")


# ---------------------------------------------------------------- pptx

SHAPES = {q("p:sp"), q("p:pic"), q("p:grpSp"), q("p:graphicFrame"), q("p:cxnSp")}


def pptx_part(root, part, rules: Rules, log: list):
    changed = False
    for sp in list(root.iter(*SHAPES)):
        if sp.getparent() is None or any(a.getparent() is None for a in sp.iterancestors() if a is not root):
            continue
        cnv = sp.find(".//" + q("p:cNvPr"))
        names = [cnv.get("name", ""), cnv.get("descr", "")] if cnv is not None else []
        text = all_text(sp)
        reason = None
        if any(is_wm_name(n) for n in names):
            reason = "워터마크 도형"
        elif rules.patterns and sp.find(".//" + q("p:ph")) is None and rules.only_pattern(text):
            reason = "지정 문구 도형"
        if reason:
            log.append(f"{part}: {reason} '{(text.strip() or (names[0] if names else ''))[:40]}' 제거")
            drop(sp)
            changed = True
    return changed


def pptx_list(root, part, found):
    if "slideMaster" not in part and "slideLayout" not in part:
        return
    for sp in root.iter(q("p:sp"), q("p:pic")):
        if sp.find(".//" + q("p:ph")) is not None:
            continue
        cnv = sp.find(".//" + q("p:cNvPr"))
        t = all_text(sp).strip()
        found.append(f"{part}: 도형 {cnv.get('name') if cnv is not None else '?'!r} 글자={t[:40]!r}")


# ---------------------------------------------------------------- xlsx

HF_TAGS = [q(f"x:{t}") for t in ("oddHeader", "oddFooter", "evenHeader", "evenFooter", "firstHeader", "firstFooter")]


def xlsx_part(root, part, rules: Rules, log: list):
    changed = False
    if "/worksheets/" in part:
        for pic in root.findall(q("x:picture")):
            log.append(f"{part}: 시트 배경 그림 제거")
            drop(pic)
            changed = True
        rx = rules.regex()
        removed_g = False
        for hf in root.iter(*HF_TAGS):
            text = hf.text or ""
            new = text.replace("&G", "")
            if new != text:
                removed_g = True
            if rx:
                new = rx.sub("", new)
            if new != text:
                # 내용이 빠진 구역의 서식 코드(&"글꼴", &12, &L/&C/&R)도 정리
                new = re.sub(r'(?:&"[^"]*"|&\d+|&[BIUSEXYO])+(?=&[LCR]|$)', "", new)
                new = re.sub(r"&[LCR](?=&[LCR]|$)", "", new)
                log.append(f"{part}: 머리글/바닥글 {etree.QName(hf).localname} 정리")
                if new:
                    hf.text = new
                else:
                    drop(hf)
                changed = True
        if removed_g:
            for el in root.findall(q("x:legacyDrawingHF")):
                drop(el)
    if "/drawings/" in part and part.endswith(".xml"):
        for anchor in list(root):
            cnv = anchor.find(".//" + q("xdr:cNvPr"))
            names = [cnv.get("name", ""), cnv.get("descr", "")] if cnv is not None else []
            text = all_text(anchor)
            if any(is_wm_name(n) for n in names) or (rules.patterns and rules.only_pattern(text)):
                log.append(f"{part}: 도형 '{(text.strip() or names[0])[:40]}' 제거")
                drop(anchor)
                changed = True
    return changed


def xlsx_list(root, part, found):
    if "/worksheets/" in part:
        if root.findall(q("x:picture")):
            found.append(f"{part}: 시트 배경 그림 있음")
        for hf in root.iter(*HF_TAGS):
            if hf.text:
                found.append(f"{part}: {etree.QName(hf).localname} = {hf.text[:60]!r}")


# ---------------------------------------------------------------- 공통 처리

def target_parts(kind: str, name: str) -> bool:
    if not name.endswith(".xml"):
        return False
    if kind == "docx":
        return re.match(r"word/(document|header\d*|footer\d*)\.xml$", name) is not None
    if kind == "pptx":
        return re.match(r"ppt/(slides|slideLayouts|slideMasters)/[^/]+\.xml$", name) is not None
    return re.match(r"xl/(worksheets|drawings)/[^/]+\.xml$", name) is not None


def process(src: Path, dst: Path, kind: str, rules: Rules, list_only: bool) -> int:
    handler = {"docx": docx_part, "pptx": pptx_part, "xlsx": xlsx_part}[kind]
    lister = {"docx": docx_list, "pptx": pptx_list, "xlsx": xlsx_list}[kind]
    parser = etree.XMLParser(huge_tree=True, remove_blank_text=False)
    log: list[str] = []
    found: list[str] = []
    new_data: dict[str, bytes] = {}

    with zipfile.ZipFile(src) as zin:
        for info in zin.infolist():
            if not target_parts(kind, info.filename):
                continue
            root = etree.fromstring(zin.read(info), parser)
            if list_only:
                lister(root, info.filename, found)
            if handler(root, info.filename, rules, log):
                new_data[info.filename] = etree.tostring(root, xml_declaration=True,
                                                         encoding="UTF-8", standalone=True)
        if list_only:
            print(f"[미리 보기] {src.name} — 실제로는 바꾸지 않았습니다")
            print("  지워질 항목:")
            for line in log or ["(자동으로 찾은 워터마크 없음)"]:
                print("   - " + line)
            if found:
                print("  머리글/바닥글·마스터에 있는 내용 (워터마크 후보, --text 로 지정 가능):")
                for line, c in Counter(found).items():
                    print("   - " + line + (f" ×{c}" if c > 1 else ""))
            return 0
        if not new_data:
            print(f"[변화 없음] {src.name}: 워터마크를 찾지 못했습니다. --list 로 후보를 보고 --text 로 지정하세요.")
            return 1
        dst.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(dst, "w") as zout:
            for info in zin.infolist():
                data = new_data.get(info.filename)
                zout.writestr(info, data if data is not None else zin.read(info))

    print(f"[완료] {src.name} → {dst}")
    for line, c in Counter(log).items():
        print("  - " + line + (f" ×{c}" if c > 1 else ""))
    return 0


def convert_legacy(src: Path, workdir: Path) -> Path:
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        sys.exit(f"{src.suffix} 파일은 LibreOffice(soffice)가 있어야 변환할 수 있습니다. "
                 f"Word/PowerPoint/Excel 에서 {CONVERT[src.suffix.lower()]} 로 다시 저장해 주세요.")
    fmt = CONVERT[src.suffix.lower()]
    subprocess.run([soffice, "--headless", "--convert-to", fmt, "--outdir", str(workdir), str(src)],
                   check=True, capture_output=True, timeout=180)
    out = workdir / f"{src.stem}.{fmt}"
    if not out.exists():
        sys.exit(f"{src.name} 변환에 실패했습니다 (hwp 는 LibreOffice 에 H2Orestart 확장이 필요할 수 있습니다)")
    print(f"[변환] {src.name} → {fmt}")
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Word/PowerPoint/Excel 워터마크 제거",
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    p.add_argument("input")
    p.add_argument("-o", "--output", help="결과 파일 (기본: 원본이름_clean.확장자)")
    p.add_argument("--text", action="append", default=[], metavar="문구", help="지울 워터마크 문구 (여러 번 가능)")
    p.add_argument("--behind-images", action="store_true", help="(docx) 머리글의 텍스트 뒤 그림도 제거")
    p.add_argument("--list", action="store_true", help="지우지 않고 후보만 보여줌")
    args = p.parse_args(argv)

    src = Path(args.input)
    if not src.is_file():
        p.error(f"파일이 없습니다: {src}")
    ext = src.suffix.lower()
    rules = Rules(args.text, args.behind_images)

    with tempfile.TemporaryDirectory() as td:
        work = src
        if ext in CONVERT:
            work = convert_legacy(src, Path(td))
            ext = work.suffix.lower()
        if ext not in KINDS:
            p.error(f"지원하지 않는 형식입니다: {src.suffix}")
        dst = Path(args.output) if args.output else src.with_name(src.stem + "_clean" + ext)
        if dst.suffix.lower() != ext:
            dst = dst.with_suffix(ext)
        return process(work, dst, KINDS[ext], rules, args.list)


if __name__ == "__main__":
    sys.exit(main())
