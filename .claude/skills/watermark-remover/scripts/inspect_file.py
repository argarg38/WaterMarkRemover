#!/usr/bin/env python3
"""숨은 문자·메타데이터 검사 (읽기 전용 — 파일을 절대 바꾸지 않는다).

텍스트(.md .txt .html .csv .json 등)
  보이지 않는 문자(제로폭), 방향 제어 문자, 유니코드 태그 문자(숨은 글자),
  변형 선택자, 제어 문자, 사용자 정의 영역 문자, 특수 공백, 다른 문자 체계가 섞인 단어(동형 문자),
  BOM, 유니코드 정규화(NFC) 여부, 줄바꿈 혼용, front matter·HTML 주석 같은 메타데이터
docx / pptx / xlsx
  문서 속성(작성자·회사·수정자 등), 사용자 지정 속성, 메모, 변경 추적, 숨김 글자 + 본문 숨은 문자
pdf
  문서 정보(/Info), XMP 메타데이터, 첨부 파일 + 추출 글자의 숨은 문자

통계적 텍스트 워터마크(AI 생성 글의 단어 선택 패턴)는 이 도구로 검사할 수 없다.

예시
  python inspect_file.py draft.md
  python inspect_file.py draft.cleaned.md
  python inspect_file.py draft.md --compare draft.cleaned.md
  python inspect_file.py draft.md --json
  python inspect_file.py /mnt/project/            # 폴더 안 지원 파일 전부 요약표
  python inspect_file.py a.md b.pdf c.docx --detail
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
import zipfile
from pathlib import Path

# ---------------------------------------------------------------- 분류 정의

CATEGORIES = {
    "zero_width": ("보이지 않는 문자(제로폭)", "화면에 안 보이지만 글자 사이에 끼어 있는 문자. 복사·검색·코드 실행을 망가뜨리고, 정보를 몰래 심는 데 쓰일 수 있음"),
    "bidi": ("방향 제어 문자", "글자 표시 방향을 바꾸는 문자. 보이는 순서와 실제 순서가 달라질 수 있음 (Trojan Source)"),
    "tags": ("유니코드 태그 문자", "보이지 않는 ASCII 글자를 숨겨 넣을 수 있는 문자. 숨은 문장이 있는지 해독해 보여줌"),
    "variation": ("변형 선택자(이모지·한자 외)", "이모지·한자 뒤가 아닌 곳에 붙은 변형 선택자. 데이터 은닉에 쓰일 수 있음"),
    "control": ("제어 문자", "탭·줄바꿈 외의 제어 문자"),
    "private_use": ("사용자 정의 영역 문자", "표준 의미가 없는 문자. 특정 글꼴·프로그램에서만 보임"),
    "odd_space": ("특수 공백", "줄바꿈 없는 공백(NBSP), 전각 공백 등 일반 공백이 아닌 공백"),
    "homoglyph": ("다른 문자 체계가 섞인 단어", "라틴 글자 단어 안에 모양이 같은 키릴/그리스 글자가 섞임 (예: 'pаypal'의 а)"),
    "bom": ("BOM", "파일 맨 앞의 바이트 순서 표시"),
    "not_nfc": ("분리 저장된 글자(NFC 아님)", "한글 자모가 분리 저장된 경우 등. 검색·비교가 어긋날 수 있음 (macOS에서 흔함)"),
    "line_endings": ("줄바꿈 혼용", "CRLF와 LF가 섞여 있음"),
}

ZERO_WIDTH = {0x200B, 0x200C, 0x200D, 0x2060, 0x2061, 0x2062, 0x2063, 0x2064, 0xFEFF,
              0x180E, 0x00AD, 0x034F, 0x115F, 0x1160, 0x3164, 0xFFA0, 0x17B4, 0x17B5}
BIDI = {0x200E, 0x200F, 0x061C} | set(range(0x202A, 0x202F)) | set(range(0x2066, 0x206A))
ODD_SPACE = {0x00A0, 0x1680, 0x202F, 0x205F, 0x3000} | set(range(0x2000, 0x200B))

CONFUSABLES = {
    # 키릴
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x", "і": "i", "ј": "j", "ѕ": "s",
    "ԁ": "d", "ӏ": "l", "һ": "h", "ԛ": "q", "ԝ": "w",
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H", "О": "O", "Р": "P", "С": "C", "Т": "T",
    "Х": "X", "І": "I", "Ј": "J", "Ѕ": "S",
    # 그리스
    "ο": "o", "α": "a", "ν": "v", "ρ": "p", "ι": "i", "κ": "k", "τ": "t", "υ": "u",
    "Ο": "O", "Α": "A", "Β": "B", "Ε": "E", "Ζ": "Z", "Η": "H", "Ι": "I", "Κ": "K", "Μ": "M", "Ν": "N",
    "Ρ": "P", "Τ": "T", "Χ": "X", "Υ": "Y",
}

TEXT_EXTS = {".md", ".markdown", ".txt", ".text", ".html", ".htm", ".csv", ".tsv", ".json", ".xml",
             ".yaml", ".yml", ".rst", ".tex", ".py", ".js", ".ts", ".srt", ".vtt", ".log", ".ini", ".toml"}
OFFICE_EXTS = {".docx", ".docm", ".pptx", ".pptm", ".xlsx", ".xlsm"}


def is_emojiish(ch: str | None) -> bool:
    if not ch:
        return False
    c = ord(ch)
    return (0x1F000 <= c <= 0x1FAFF or 0x2600 <= c <= 0x27BF or 0x2300 <= c <= 0x23FF
            or 0x2B00 <= c <= 0x2BFF or 0x1F3FB <= c <= 0x1F3FF or c in (0x00A9, 0x00AE, 0x203C, 0x2049,
                                                                          0x2122, 0x2139, 0x3030, 0x303D)
            or ch in "0123456789#*" or c == 0xFE0F or c == 0x20E3)


def is_cjk(ch: str | None) -> bool:
    return bool(ch) and (0x3400 <= ord(ch) <= 0x9FFF or 0x20000 <= ord(ch) <= 0x3FFFF or 0xF900 <= ord(ch) <= 0xFAFF)


def classify(text: str, i: int) -> str | None:
    """text[i] 가 의심 문자면 분류 key, 아니면 None. 이모지 결합용 ZWJ·변형 선택자는 정상으로 본다."""
    ch = text[i]
    c = ord(ch)
    prev = text[i - 1] if i > 0 else None
    nxt = text[i + 1] if i + 1 < len(text) else None
    if c == 0xFEFF and i == 0:
        return "bom"
    if c == 0x200D and is_emojiish(prev) and is_emojiish(nxt):
        return None
    if c in ZERO_WIDTH:
        return "zero_width"
    if c in BIDI:
        return "bidi"
    if 0xE0000 <= c <= 0xE007F:
        # 국기 이모지(🏴 + 태그)는 정상
        j = i
        while j > 0 and 0xE0000 <= ord(text[j - 1]) <= 0xE007F:
            j -= 1
        return None if j > 0 and ord(text[j - 1]) == 0x1F3F4 else "tags"
    if 0xFE00 <= c <= 0xFE0F:
        return None if is_emojiish(prev) or is_cjk(prev) else "variation"
    if 0xE0100 <= c <= 0xE01EF:
        return None if is_cjk(prev) else "variation"
    if c in ODD_SPACE:
        return "odd_space"
    if (c < 0x20 and ch not in "\t\n\r") or 0x7F <= c <= 0x9F:
        return "control"
    if 0xE000 <= c <= 0xF8FF or 0xF0000 <= c <= 0x10FFFD:
        return "private_use"
    return None


def homoglyph_words(text: str):
    for m in re.finditer(r"\w+", text):
        w = m.group()
        has_latin = any("a" <= ch.lower() <= "z" for ch in w)
        odd = [ch for ch in w if ch in CONFUSABLES]
        if has_latin and odd:
            yield m.start(), w, odd


def decode_tags(text: str) -> list[str]:
    hidden, cur = [], []
    for ch in text:
        c = ord(ch)
        if 0xE0020 <= c <= 0xE007E:
            cur.append(chr(c - 0xE0000))
        elif cur:
            hidden.append("".join(cur))
            cur = []
    if cur:
        hidden.append("".join(cur))
    return hidden


def line_col(text: str, idx: int) -> tuple[int, int]:
    line = text.count("\n", 0, idx) + 1
    col = idx - (text.rfind("\n", 0, idx) + 1) + 1
    return line, col


def char_name(ch: str) -> str:
    return f"U+{ord(ch):04X} {unicodedata.name(ch, '이름 없음')}"


# ---------------------------------------------------------------- 텍스트 검사

def scan_text(text: str, max_examples: int = 5) -> dict:
    findings: dict[str, dict] = {}

    def add(key, idx, detail):
        f = findings.setdefault(key, {"count": 0, "examples": [], "chars": {}})
        f["count"] += 1
        if len(f["examples"]) < max_examples:
            ln, col = line_col(text, idx)
            f["examples"].append(f"{ln}행 {col}열: {detail}")

    for i, ch in enumerate(text):
        key = classify(text, i)
        if key:
            add(key, i, char_name(ch))
            name = char_name(ch)
            findings[key]["chars"][name] = findings[key]["chars"].get(name, 0) + 1

    for idx, word, odd in homoglyph_words(text):
        add("homoglyph", idx, f"'{word}' 안의 " + ", ".join(f"{c}({char_name(c)})" for c in odd))

    if "tags" in findings:
        findings["tags"]["hidden_text"] = decode_tags(text)

    if unicodedata.normalize("NFC", text) != text:
        n = max(1, len(text) - len(unicodedata.normalize("NFC", text)))
        idx = next(i for i, (a, b) in enumerate(zip(text, unicodedata.normalize("NFC", text))) if a != b) \
            if any(a != b for a, b in zip(text, unicodedata.normalize("NFC", text))) else 0
        ln, col = line_col(text, idx)
        findings["not_nfc"] = {"count": n, "examples": [f"{ln}행 {col}열부터 (NFC로 합치면 {n}자 줄어듦)"], "chars": {}}

    crlf = text.count("\r\n")
    lf = text.count("\n") - crlf
    if crlf and lf:
        findings["line_endings"] = {"count": min(crlf, lf), "examples": [f"CRLF {crlf}줄, LF {lf}줄"], "chars": {}}
    return findings


def text_metadata(text: str, suffix: str) -> dict:
    meta: dict = {}
    body = text.lstrip("﻿")
    fm = re.match(r"^---\s*\n(.*?)\n(---|\.\.\.)\s*(\n|$)", body, re.S)
    if fm:
        keys = re.findall(r"^([A-Za-z0-9_\-가-힣]+)\s*:", fm.group(1), re.M)
        meta["front_matter"] = {"lines": fm.group(1).count("\n") + 1, "keys": keys}
    comments = re.findall(r"<!--(.*?)-->", text, re.S)
    if comments:
        meta["html_comments"] = [c.strip()[:80] for c in comments[:10]] + (["…"] if len(comments) > 10 else [])
        meta["html_comment_count"] = len(comments)
    md_comments = re.findall(r"^\[(?://|comment|_)\]:\s*#\s*(.*)$", text, re.M)
    if md_comments:
        meta["markdown_comments"] = [c[:80] for c in md_comments[:10]]
    if suffix in (".html", ".htm"):
        metas = re.findall(r"<meta\s+[^>]*>", text, re.I)
        if metas:
            meta["html_meta_tags"] = [m[:100] for m in metas[:10]]
    return meta


def read_text(path: Path) -> tuple[str, str]:
    raw = path.read_bytes()
    for enc in ("utf-8", "utf-16", "cp949"):
        try:
            if enc == "utf-16" and not raw.startswith((b"\xff\xfe", b"\xfe\xff")):
                continue
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8(깨진 바이트 대체)"


# ---------------------------------------------------------------- 오피스·PDF

def office_inspect(path: Path) -> tuple[str, dict]:
    from xml.etree import ElementTree as ET
    meta: dict = {}
    texts = []
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        for part, label in (("docProps/core.xml", "문서 속성"), ("docProps/app.xml", "앱 속성"), ("docProps/custom.xml", "사용자 지정 속성")):
            if part in names:
                root = ET.fromstring(z.read(part))
                props = {}
                for el in root.iter():
                    tag = el.tag.split("}")[-1]
                    if el.text and el.text.strip() and len(el) == 0:
                        props[tag] = el.text.strip()[:80]
                if part.endswith("custom.xml"):
                    props = {p.get("name"): "".join(p.itertext())[:80] for p in root}
                keep = {k: v for k, v in props.items() if k in ("creator", "lastModifiedBy", "title", "subject", "description",
                        "keywords", "category", "created", "modified", "Company", "Manager", "Application", "AppVersion",
                        "Template", "TotalTime", "revision")} if not part.endswith("custom.xml") else props
                if keep:
                    meta[label] = keep
        comments = [n for n in names if re.search(r"(comments\d*\.xml|/comments/)", n)]
        if comments:
            meta["메모(댓글) 파트"] = comments
        for n in names:
            if re.match(r"(word/(document|header\d*|footer\d*|footnotes|endnotes)|ppt/slides/slide\d+|xl/sharedStrings)\.xml$", n):
                data = z.read(n).decode("utf-8", errors="replace")
                if n == "word/document.xml":
                    ins, dels = len(re.findall(r"<w:ins\b", data)), len(re.findall(r"<w:del\b", data))
                    if ins or dels:
                        meta["변경 추적"] = f"삽입 {ins}곳, 삭제 {dels}곳 (수락/거부 안 된 상태)"
                    vanish = len(re.findall(r"<w:vanish/>", data))
                    if vanish:
                        meta["숨김 글자 서식"] = f"{vanish}곳"
                texts += re.findall(r"<(?:w:|a:)?t(?:\s[^>]*)?>([^<]*)</(?:w:|a:)?t>", data)
    import html
    return html.unescape("\n".join(texts)), meta


def pdf_inspect(path: Path) -> tuple[str, dict]:
    from pypdf import PdfReader
    r = PdfReader(str(path))
    meta: dict = {}
    if r.is_encrypted:
        try:
            r.decrypt("")
        except Exception:
            return "", {"암호": "암호가 걸려 있어 검사할 수 없음"}
    info = r.metadata or {}
    if info:
        meta["문서 정보(/Info)"] = {k.lstrip("/"): str(v)[:80] for k, v in info.items()}
    root = r.trailer["/Root"]
    if "/Metadata" in root:
        xmp = root["/Metadata"].get_object().get_data()
        tools = re.findall(rb"<(?:xmp:CreatorTool|pdf:Producer)>([^<]*)<", xmp)
        meta["XMP 메타데이터"] = f"{len(xmp)}바이트" + (f", 도구: {', '.join(t.decode('utf-8', 'replace') for t in tools)}" if tools else "")
    names = root.get("/Names")
    if names and "/EmbeddedFiles" in names.get_object():
        meta["첨부 파일"] = "있음"
    text = "\n".join((p.extract_text() or "") for p in r.pages)
    return text, meta


# ---------------------------------------------------------------- 보고

STAT_NOTE = (
    "통계적 텍스트 워터마크(AI가 글을 만들 때 단어 선택 확률에 심는 패턴)는 이 검사 범위 밖입니다.\n"
    "  · 눈에 보이는 문자나 메타데이터가 아니라 '어떤 단어를 골랐는가'의 통계에 들어 있어서, 만든 쪽의 비밀 키·전용 탐지기 없이는\n"
    "    있는지 없는지 확인할 수 없습니다.\n"
    "  · 숨은 문자 0건은 '숨은 문자가 없다'는 뜻일 뿐, 통계적 워터마크가 없다거나 지워졌다는 뜻이 아닙니다."
)


def inspect(path: Path) -> dict:
    ext = path.suffix.lower()
    if ext in OFFICE_EXTS:
        text, meta = office_inspect(path)
        kind, enc = "office", None
    elif ext == ".pdf":
        text, meta = pdf_inspect(path)
        kind, enc = "pdf", None
    else:
        text, enc = read_text(path)
        meta = text_metadata(text, ext)
        kind = "text"
    findings = scan_text(text)
    if kind != "text":
        findings.pop("line_endings", None)
        findings.pop("bom", None)
    return {"file": str(path), "kind": kind, "encoding": enc, "chars": len(text),
            "findings": findings, "metadata": meta}


def print_report(rep: dict) -> None:
    print(f"■ 검사 대상: {rep['file']}  ({rep['kind']}, {rep['chars']:,}자" + (f", 인코딩 {rep['encoding']}" if rep["encoding"] else "") + ")")
    print("  ※ 읽기 전용 검사입니다. 파일은 바뀌지 않았습니다.\n")
    print("[1] 숨은 문자")
    f = rep["findings"]
    if not f:
        print("  발견 없음")
    for key, (label, desc) in CATEGORIES.items():
        if key not in f:
            continue
        item = f[key]
        print(f"  ● {label}: {item['count']}건")
        print(f"    - 무엇: {desc}")
        if item.get("chars"):
            print("    - 종류: " + ", ".join(f"{n} ×{c}" for n, c in sorted(item["chars"].items(), key=lambda x: -x[1])[:6]))
        for ex in item["examples"]:
            print(f"    - 위치: {ex}")
        if item.get("hidden_text"):
            for h in item["hidden_text"][:5]:
                print(f"    - 해독된 숨은 글자: {h!r}")
    print("\n[2] 메타데이터")
    if not rep["metadata"]:
        print("  발견 없음")
    labels = {"front_matter": "YAML front matter", "html_comments": "HTML 주석", "markdown_comments": "마크다운 주석",
              "html_meta_tags": "HTML meta 태그"}
    for k, v in rep["metadata"].items():
        if k == "html_comment_count":
            continue
        if k == "front_matter":
            print(f"  ● YAML front matter (맨 앞 --- 블록): {v['lines']}줄, 항목 {', '.join(v['keys']) or '-'}")
            continue
        k = labels.get(k, k)
        if isinstance(v, dict):
            print(f"  ● {k}:")
            for kk, vv in v.items():
                print(f"    - {kk}: {vv}")
        elif isinstance(v, list):
            print(f"  ● {k}: {len(v)}개")
            for vv in v[:10]:
                print(f"    - {vv}")
        else:
            print(f"  ● {k}: {v}")
    print("\n[3] 통계적 텍스트 워터마크")
    print("  " + STAT_NOTE)


def summary_counts(rep: dict) -> dict:
    counts = {CATEGORIES[k][0]: v["count"] for k, v in rep["findings"].items()}
    m = rep["metadata"]
    if "front_matter" in m:
        counts["front matter"] = len(m["front_matter"]["keys"]) or 1
    if "html_comment_count" in m:
        counts["HTML 주석"] = m["html_comment_count"]
    if "markdown_comments" in m:
        counts["마크다운 주석"] = len(m["markdown_comments"])
    for k in m:
        if k not in ("front_matter", "html_comments", "html_comment_count", "markdown_comments"):
            counts[k] = 1
    return counts


def pad(s: str, width: int) -> str:
    w = sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)
    return s + " " * max(0, width - w)


def print_compare(a: dict, b: dict) -> None:
    ca, cb = summary_counts(a), summary_counts(b)
    keys = list(dict.fromkeys(list(ca) + list(cb)))
    print(f"■ 전후 비교: {Path(a['file']).name} → {Path(b['file']).name}\n")
    w = max([sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in k) for k in keys] + [8])
    print(f"  {pad('항목', w)}  {'전':>5}  {'후':>5}  결과")
    for k in keys:
        x, y = ca.get(k, 0), cb.get(k, 0)
        res = "제거됨" if x and not y else ("줄어듦" if y < x else ("그대로" if x == y and x else ("새로 생김" if y > x else "")))
        print(f"  {pad(k, w)}  {x:>5}  {y:>5}  {res}")
    if not keys:
        print("  두 파일 모두 발견 항목 없음")
    print(f"\n  글자 수: {a['chars']:,} → {b['chars']:,}")
    print("\n  " + STAT_NOTE)


SUPPORTED = TEXT_EXTS | OFFICE_EXTS | {".pdf"}


def collect(paths: list[str]) -> list[Path]:
    """파일·폴더를 받아 검사할 파일 목록을 만든다 (폴더는 하위까지, 지원 형식만)."""
    out = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            out += sorted(f for f in p.rglob("*") if f.is_file() and f.suffix.lower() in SUPPORTED
                          and ".cleaned." not in f.name and "_clean." not in f.name)
        elif p.is_file():
            out.append(p)
        else:
            print(f"[건너뜀] 없는 경로: {p}", file=sys.stderr)
    return out


def print_summary(reports: list[dict]) -> None:
    print(f"■ 여러 파일 요약 ({len(reports)}개) — 읽기 전용 검사, 파일은 바뀌지 않았습니다\n")
    names = [Path(r["file"]).name for r in reports]
    w = max([sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in n) for n in names] + [8])
    print(f"  {pad('파일', w)}  {'숨은 문자':>8}  메타데이터 / 주요 항목")
    for r, n in zip(reports, names):
        if "error" in r:
            print(f"  {pad(n, w)}  {'-':>8}  검사 실패: {r['error']}")
            continue
        hidden = sum(v["count"] for k, v in r["findings"].items() if k not in ("line_endings",))
        kinds = [CATEGORIES[k][0] for k in r["findings"]]
        meta = [k if not k.startswith(("front", "html", "markdown")) else
                {"front_matter": "front matter", "html_comments": "HTML 주석", "markdown_comments": "마크다운 주석",
                 "html_meta_tags": "meta 태그"}.get(k, "") for k in r["metadata"] if k != "html_comment_count"]
        detail = ", ".join(kinds + meta) or "발견 없음"
        print(f"  {pad(n, w)}  {hidden:>8}  {detail}")
    print("\n  파일별 자세한 내용: python inspect_file.py <파일>  (또는 --detail)")
    print("\n  " + STAT_NOTE)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="숨은 문자·메타데이터 검사 (읽기 전용)",
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    p.add_argument("files", nargs="+", help="파일 또는 폴더 (여러 개 가능)")
    p.add_argument("--compare", metavar="FILE", help="정돈 후 파일과 전후 비교표 출력 (파일 하나일 때)")
    p.add_argument("--detail", action="store_true", help="여러 파일일 때 요약표 대신 파일별 전체 보고")
    p.add_argument("--json", action="store_true", help="결과를 JSON으로 출력")
    args = p.parse_args(argv)

    files = collect(args.files)
    if not files:
        p.error("검사할 파일이 없습니다")

    if args.compare:
        if len(files) != 1:
            p.error("--compare 는 원본 파일 하나와 함께 쓰세요")
        other = Path(args.compare)
        if not other.is_file():
            p.error(f"파일이 없습니다: {other}")
        rep, rep2 = inspect(files[0]), inspect(other)
        if args.json:
            print(json.dumps({"before": rep, "after": rep2}, ensure_ascii=False, indent=2))
        else:
            print_compare(rep, rep2)
        return 0

    reports = []
    for f in files:
        try:
            reports.append(inspect(f))
        except Exception as e:  # 한 파일이 깨져도 나머지는 계속
            reports.append({"file": str(f), "error": str(e)[:80]})
    if args.json:
        print(json.dumps(reports[0] if len(reports) == 1 else reports, ensure_ascii=False, indent=2))
    elif len(reports) == 1 and "error" not in reports[0]:
        print_report(reports[0])
    elif args.detail:
        for r in reports:
            if "error" in r:
                print(f"■ {r['file']}: 검사 실패 ({r['error']})\n")
            else:
                print_report(r)
                print()
    else:
        print_summary(reports)
    return 0


if __name__ == "__main__":
    sys.exit(main())
