#!/usr/bin/env python3
"""PDF 워터마크 제거.

PDF 안의 워터마크 '객체'를 찾아 빼낸다. 본문 글자·이미지는 그대로 남는다.

자동으로 찾는 것 (항상)
  - 워터마크 주석(/Watermark annotation)
  - Acrobat·Word 등이 '워터마크'로 표시해 둔 내용 (/Artifact /Watermark, 'Watermark' 레이어(OCG))
  - 워터마크로 표시된 Form XObject (/PieceInfo ... /Watermark)
  - 대각선으로 기울어진 큰 글씨, 또는 반투명한 큰 글씨 (--no-heuristic 으로 끔)

직접 지정
  --text 문구      그 문구를 그리는 글자를 지움 (여러 번 가능, 대소문자·공백 무시)

스캔본처럼 워터마크가 그림에 박혀 있으면
  --raster [이미지 옵션]   페이지를 이미지로 바꿔 remove_watermark.py 와 같은 방식으로 지운다

예시
  python remove_pdf_watermark.py doc.pdf --list
  python remove_pdf_watermark.py doc.pdf --text CONFIDENTIAL --preview
  python remove_pdf_watermark.py scan.pdf --raster --auto --region center --preview
"""

from __future__ import annotations

import argparse
import io
import math
import re
import sys
from collections import Counter
from pathlib import Path

try:
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import (ArrayObject, ContentStream, DictionaryObject, FloatObject,
                               IndirectObject, NameObject, NumberObject, StreamObject)
except ImportError:  # pragma: no cover
    sys.exit("필요한 패키지가 없습니다: pip install pypdf")

HERE = Path(__file__).resolve().parent
WM_WORDS = ("watermark", "워터마크")

SHOW_OPS = {b"Tj", b"TJ", b"'", b'"'}
PAINT_OPS = {b"S", b"s", b"f", b"F", b"f*", b"B", b"B*", b"b", b"b*"}
DRAW_OPS = {b"Do", b"sh", b"INLINE IMAGE"}


# ---------------------------------------------------------------- 공통 도우미

def norm(s: str) -> str:
    return re.sub(r"\s+", "", s).lower()


def is_wm_name(value) -> bool:
    s = str(value).lower()
    return any(w in s for w in WM_WORDS)


def resolve(obj):
    return obj.get_object() if isinstance(obj, IndirectObject) else obj


def inherited(page, key):
    node = page
    while node is not None:
        if key in node:
            return resolve(node[key])
        node = resolve(node.get("/Parent"))
    return None


def mat_mul(m, n):
    a, b, c, d, e, f = m
    a2, b2, c2, d2, e2, f2 = n
    return (a * a2 + b * c2, a * b2 + b * d2, c * a2 + d * c2, c * b2 + d * d2,
            e * a2 + f * c2 + e2, e * b2 + f * d2 + f2)


IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


# ---------------------------------------------------------------- 글꼴 → 유니코드

class FontDecoder:
    """ToUnicode CMap 을 읽어 PDF 문자열을 사람이 읽는 글자로 바꾼다."""

    def __init__(self, font):
        self.map: dict[bytes, str] = {}
        self.lengths: list[int] = []
        font = resolve(font) or {}
        self.two_byte = font.get("/Subtype") == "/Type0"
        tu = resolve(font.get("/ToUnicode"))
        if isinstance(tu, StreamObject):
            try:
                self._parse(tu.get_data())
            except Exception:
                self.map = {}
        self.lengths = sorted({len(k) for k in self.map}, reverse=True) or ([2] if self.two_byte else [1])

    @staticmethod
    def _hex_to_str(h: bytes) -> str:
        raw = bytes.fromhex(h.decode())
        try:
            return raw.decode("utf-16-be")
        except UnicodeDecodeError:
            return raw.decode("latin-1")

    def _parse(self, data: bytes) -> None:
        for block in re.findall(rb"beginbfchar(.*?)endbfchar", data, re.S):
            for src, dst in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]*)>", block):
                self.map[bytes.fromhex(src.decode())] = self._hex_to_str(dst)
        for block in re.findall(rb"beginbfrange(.*?)endbfrange", data, re.S):
            for lo, hi, rest in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*(\[[^\]]*\]|<[0-9A-Fa-f]*>)", block):
                n = len(lo) // 2
                lo_i, hi_i = int(lo, 16), int(hi, 16)
                if hi_i - lo_i > 65535:
                    continue
                if rest.startswith(b"["):
                    dsts = re.findall(rb"<([0-9A-Fa-f]*)>", rest)
                    for i, d in enumerate(dsts):
                        self.map[(lo_i + i).to_bytes(n, "big")] = self._hex_to_str(d)
                else:
                    base = bytes.fromhex(rest[1:-1].decode())
                    for i in range(hi_i - lo_i + 1):
                        dst = base[:-1] + bytes([(base[-1] + i) & 0xFF]) if base else b""
                        try:
                            s = dst.decode("utf-16-be")
                        except UnicodeDecodeError:
                            s = dst.decode("latin-1")
                        self.map[(lo_i + i).to_bytes(n, "big")] = s

    def decode(self, raw: bytes) -> str:
        if not self.map:
            if self.two_byte:
                return "".join("?" for _ in range(len(raw) // 2))
            return raw.decode("cp1252", errors="replace")
        out, i = [], 0
        while i < len(raw):
            for n in self.lengths:
                chunk = raw[i:i + n]
                if chunk in self.map:
                    out.append(self.map[chunk])
                    i += n
                    break
            else:
                out.append(chr(raw[i]) if not self.two_byte else "?")
                i += 1 if not self.two_byte else 2
        return "".join(out)


def operand_bytes(o) -> bytes:
    if hasattr(o, "original_bytes"):
        return o.original_bytes
    if isinstance(o, bytes):
        return o
    return str(o).encode("latin-1", errors="replace")


def show_text(op, operands, decoder: FontDecoder) -> str:
    if op == b"TJ":
        return "".join(decoder.decode(operand_bytes(x)) for x in operands[0] if not isinstance(x, (int, float)))
    if op in (b"Tj", b"'"):
        return decoder.decode(operand_bytes(operands[0]))
    if op == b'"':
        return decoder.decode(operand_bytes(operands[2]))
    return ""


# ---------------------------------------------------------------- 정리기

class Cleaner:
    def __init__(self, writer: PdfWriter, patterns: list[str], heuristic: bool, dry: bool):
        self.writer = writer
        self.patterns = [norm(p) for p in patterns if norm(p)]
        self.heuristic = heuristic
        self.dry = dry
        self.log: list[str] = []
        self.done_forms: set = set()
        self.decoders: dict = {}
        self.text_seen: Counter = Counter()  # --list 용
        self.page_area = 0.0

    # ---- 판정
    def ocg_is_wm(self, obj) -> bool:
        obj = resolve(obj)
        if not isinstance(obj, DictionaryObject):
            return False
        if obj.get("/Type") == "/OCG":
            return is_wm_name(obj.get("/Name", ""))
        if obj.get("/Type") == "/OCMD":
            ocgs = resolve(obj.get("/OCGs"))
            ocgs = ocgs if isinstance(ocgs, ArrayObject) else [ocgs]
            return any(self.ocg_is_wm(o) for o in ocgs if o is not None)
        return False

    def props_is_wm(self, tag, props, resources) -> bool:
        if isinstance(props, NameObject):
            prop_res = resolve((resources or {}).get("/Properties")) or {}
            props = resolve(prop_res.get(props))
        props = resolve(props)
        if not isinstance(props, DictionaryObject):
            return False
        if tag == "/Artifact" and props.get("/Subtype") == "/Watermark":
            return True
        return self.ocg_is_wm(props)

    def xobject_is_wm(self, xobj) -> bool:
        piece = resolve(xobj.get("/PieceInfo"))
        if isinstance(piece, DictionaryObject):
            for v in piece.values():
                priv = resolve(resolve(v).get("/Private")) if isinstance(resolve(v), DictionaryObject) else None
                if priv == "/Watermark" or (isinstance(priv, DictionaryObject) and is_wm_name(priv)):
                    return True
            if "/ADBE_CompoundType" in piece and is_wm_name(piece):
                return True
        return self.ocg_is_wm(xobj.get("/OC"))

    def big_outline_form(self, xobj, ctm) -> bool:
        """글자 없이 선/면으로만 된 Form 이 페이지의 10% 이상을 덮는가 (윤곽선으로 바뀐 워터마크 글자)."""
        if xobj.get("/Subtype") != "/Form" or not self.page_area:
            return False
        try:
            data = xobj.get_data()
        except Exception:
            return False
        if re.search(rb"(?<![A-Za-z])(BT|Do|BI)(?![A-Za-z])", data):
            return False
        x0, y0, x1, y1 = (float(v) for v in xobj.get("/BBox", [0, 0, 0, 0]))
        m = [float(v) for v in xobj.get("/Matrix", [1, 0, 0, 1, 0, 0])]
        area = abs(x1 - x0) * abs(y1 - y0) * abs(m[0] * m[3] - m[1] * m[2]) * abs(ctm[0] * ctm[3] - ctm[1] * ctm[2])
        return area >= 0.10 * self.page_area

    def text_matches(self, text: str) -> str | None:
        t = norm(text)
        if not t:
            return None
        for p in self.patterns:
            if p in t:
                return p
        return None

    def only_pattern(self, text: str) -> bool:
        t = norm(text)
        return bool(t) and any(t.replace(p, "") == "" for p in self.patterns)

    def decoder(self, resources, font_name):
        fonts = resolve((resources or {}).get("/Font")) or {}
        font = resolve(fonts.get(font_name))
        key = id(font)
        if key not in self.decoders:
            self.decoders[key] = FontDecoder(font)
        return self.decoders[key]

    # ---- 본체: content stream 한 개 처리. 바뀐 ContentStream 또는 None 반환
    def clean_stream(self, stream_obj, resources, where: str):
        try:
            cs = ContentStream(stream_obj, self.writer)
        except Exception as e:
            self.log.append(f"{where}: 내용을 읽지 못해 건너뜀 ({e})")
            return None
        ops = cs.operations
        new_ops = []
        changed = False

        mc_stack: list[bool] = []          # 각 marked-content 블록이 워터마크인지
        gs_stack = []
        ctm, alpha = IDENTITY, 1.0
        font_name, font_size = None, 0.0
        in_bt = False
        bt_buf: list = []                  # (operands, op, text, line_key)
        tm = tlm = IDENTITY
        leading = 0.0
        shows: list = []                   # 문구 매칭용: (new_ops 위치, 글자, 줄 key, 블록 번호)
        block_no = 0

        def in_wm():
            return any(mc_stack)

        def replacement(operands, op):
            if op == b"'":
                return [([], b"T*")]
            if op == b'"':
                return [([operands[0]], b"Tw"), ([operands[1]], b"Tc"), ([], b"T*")]
            return []

        def flush_bt():
            nonlocal changed
            block_text = "".join(t for _, _, t, _ in bt_buf)
            self.text_seen[(block_text.strip(), round(math.degrees(math.atan2(tm_for_block[1], tm_for_block[0]))))] += 1
            drop_all = False
            if self.heuristic and norm(block_text):
                a, b = tm_for_block[0], tm_for_block[1]
                ang = abs(math.degrees(math.atan2(b, a))) % 90
                size = font_size_for_block * math.hypot(a, b)
                diagonal = 15 <= ang <= 75
                if (diagonal and size >= 18) or (alpha_for_block < 0.9 and size >= 24):
                    drop_all = True
                    why = "기울어진" if diagonal else "반투명"
                    self.log.append(f"{where}: {why} 큰 글씨 '{block_text.strip()[:40]}' (크기 {size:.0f}pt) 제거")
            for operands, op, text, key in bt_buf:
                if op in SHOW_OPS and drop_all:
                    changed = True
                    new_ops.extend(replacement(operands, op))
                    continue
                if op in SHOW_OPS and text:
                    shows.append((len(new_ops), text, key, block_no))
                new_ops.append((operands, op))

        tm_for_block, font_size_for_block, alpha_for_block = IDENTITY, 0.0, 1.0

        for operands, op in ops:
            # --- 상태 추적
            if op == b"q":
                gs_stack.append((ctm, alpha, font_name, font_size))
            elif op == b"Q" and gs_stack:
                ctm, alpha, font_name, font_size = gs_stack.pop()
            elif op == b"cm" and len(operands) == 6:
                ctm = mat_mul(tuple(float(x) for x in operands), ctm)
            elif op == b"gs" and operands:
                egs = resolve(resolve((resources or {}).get("/ExtGState") or {}).get(operands[0]))
                if isinstance(egs, DictionaryObject) and "/ca" in egs:
                    alpha = float(egs["/ca"])
            elif op == b"Tf" and len(operands) == 2:
                font_name, font_size = operands[0], float(operands[1])
            elif op == b"TL" and operands:
                leading = float(operands[0])
            elif op == b"Tm" and len(operands) == 6:
                tm = tlm = tuple(float(x) for x in operands)
            elif op in (b"Td", b"TD") and len(operands) == 2:
                tx, ty = float(operands[0]), float(operands[1])
                if op == b"TD":
                    leading = -ty
                tm = tlm = mat_mul((1, 0, 0, 1, tx, ty), tlm)
            elif op in (b"T*", b"'", b'"'):
                tm = tlm = mat_mul((1, 0, 0, 1, 0, -leading), tlm)

            # --- marked content
            if op in (b"BDC", b"BMC"):
                wm = op == b"BDC" and len(operands) == 2 and self.props_is_wm(operands[0], operands[1], resources)
                if wm and not in_wm():
                    self.log.append(f"{where}: 워터마크로 표시된 영역 제거")
                mc_stack.append(wm)
            elif op == b"EMC" and mc_stack:
                mc_stack.pop()

            # --- 워터마크 블록 안: 그리기 명령만 무력화 (상태 명령은 유지)
            if in_wm():
                if op in SHOW_OPS or op in DRAW_OPS:
                    changed = True
                    new_ops.extend(replacement(operands, op))
                    continue
                if op in PAINT_OPS:
                    changed = True
                    new_ops.append(([], b"n"))
                    continue

            # --- XObject
            if op == b"Do" and operands:
                xobjs = resolve((resources or {}).get("/XObject")) or {}
                xobj = resolve(xobjs.get(operands[0]))
                if isinstance(xobj, StreamObject):
                    if self.xobject_is_wm(xobj):
                        self.log.append(f"{where}: 워터마크 개체 {operands[0]} 제거")
                        changed = True
                        continue
                    if self.heuristic and alpha < 0.9 and self.big_outline_form(xobj, ctm):
                        self.log.append(f"{where}: 반투명 큰 도형(글자 윤곽) {operands[0]} 제거")
                        changed = True
                        continue
                    if xobj.get("/Subtype") == "/Form":
                        self.clean_form(xobjs.get(operands[0]), xobj, resources, f"{where}/{operands[0]}")

            # --- 텍스트 블록 모으기
            if op == b"BT":
                in_bt, bt_buf, tm, tlm = True, [], IDENTITY, IDENTITY
                block_no += 1
                new_ops.append((operands, op))
                continue
            if in_bt:
                text, key = "", None
                if op in SHOW_OPS:
                    m = mat_mul(tm, ctm)
                    tm_for_block = m
                    font_size_for_block, alpha_for_block = font_size, alpha
                    key = (round(m[5] / 2), round(math.degrees(math.atan2(m[1], m[0]))))
                    if font_name is not None:
                        try:
                            text = show_text(op, operands, self.decoder(resources, font_name))
                        except Exception:
                            text = ""
                if op == b"ET":
                    in_bt = False
                    flush_bt()
                    new_ops.append((operands, op))
                else:
                    bt_buf.append((operands, op, text, key))
                continue

            new_ops.append((operands, op))

        if in_bt:  # ET 없이 끝난 비정상 스트림
            new_ops += [(o, p) for o, p, _, _ in bt_buf]

        # --- 지정 문구: 같은 줄(또는 같은 블록)에 흩어진 조각을 이어 붙여 찾는다
        if self.patterns and shows:
            remove: set[int] = set()
            groups: dict = {}
            for rec in shows:
                groups.setdefault(("line", rec[2]), []).append(rec)
                groups.setdefault(("block", rec[3]), []).append(rec)
            for recs in groups.values():
                spans, joined = [], ""
                for rec in recs:
                    t = norm(rec[1])
                    spans.append((len(joined), len(joined) + len(t), rec[0]))
                    joined += t
                for pat in self.patterns:
                    start = joined.find(pat)
                    while start != -1:
                        end = start + len(pat)
                        remove.update(idx for s0, s1, idx in spans if s0 < end and s1 > start)
                        start = joined.find(pat, end)
            if remove:
                changed = True
                texts = {rec[0]: rec[1] for rec in shows}
                self.log.append(f"{where}: 문구 '{''.join(texts[i] for i in sorted(remove)).strip()[:50]}' 제거")
                rebuilt = []
                for i, (operands, op) in enumerate(new_ops):
                    rebuilt.extend(replacement(operands, op) if i in remove else [(operands, op)])
                new_ops = rebuilt

        if not changed:
            return None
        cs.operations = new_ops
        return cs

    def clean_form(self, ref, xobj, parent_res, where):
        key = ref.idnum if isinstance(ref, IndirectObject) else id(xobj)
        if key in self.done_forms:
            return
        self.done_forms.add(key)
        res = resolve(xobj.get("/Resources")) or parent_res
        cs = self.clean_stream(xobj, res, where)
        if cs is not None and not self.dry:
            data = cs.get_data()
            try:
                xobj.set_data(data)
            except Exception:  # Flate 외 필터: 압축을 풀어 그대로 저장
                for k in ("/Filter", "/DecodeParms"):
                    if k in xobj:
                        del xobj[k]
                xobj._data = data

    def clean_page(self, i, page):
        where = f"{i + 1}쪽"
        box = page.mediabox
        self.page_area = abs(float(box.width) * float(box.height))
        # 주석
        annots = resolve(page.get("/Annots"))
        if isinstance(annots, ArrayObject):
            keep = ArrayObject()
            for a in annots:
                ad = resolve(a)
                sub = ad.get("/Subtype") if isinstance(ad, DictionaryObject) else None
                contents = str(ad.get("/Contents", "")) if isinstance(ad, DictionaryObject) else ""
                if sub == "/Watermark" or (isinstance(ad, DictionaryObject) and self.ocg_is_wm(ad.get("/OC"))):
                    self.log.append(f"{where}: 워터마크 주석 제거")
                    continue
                if sub in ("/Stamp", "/FreeText") and self.patterns and self.text_matches(contents):
                    self.log.append(f"{where}: 도장/글상자 주석 '{contents[:40]}' 제거")
                    continue
                keep.append(a)
            if len(keep) != len(annots) and not self.dry:
                page[NameObject("/Annots")] = keep

        resources = inherited(page, "/Resources")
        contents = page.get_contents()
        if contents is None:
            return
        cs = self.clean_stream(contents, resources, where)
        if cs is not None and not self.dry:
            page.replace_contents(cs)


# ---------------------------------------------------------------- 래스터(스캔본) 모드

def render_pages(path: Path, dpi: int, indices=None):
    from PIL import Image
    try:
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(str(path))
        idx = range(len(pdf)) if indices is None else indices
        return {i: pdf[i].render(scale=dpi / 72).to_pil().convert("RGB") for i in idx}
    except ImportError:
        import subprocess, tempfile
        out = {}
        with tempfile.TemporaryDirectory() as td:
            subprocess.run(["pdftoppm", "-r", str(dpi), "-png", str(path), f"{td}/p"], check=True)
            files = sorted(Path(td).glob("p-*.png"), key=lambda f: int(f.stem.split("-")[1]))
            for n, f in enumerate(files):
                if indices is None or n in indices:
                    out[n] = Image.open(f).convert("RGB")
        return out


def parse_pages(spec: str | None, total: int):
    if not spec:
        return None
    pages = set()
    for part in spec.split(","):
        if "-" in part:
            a, b = part.split("-")
            pages.update(range(int(a) - 1, int(b)))
        else:
            pages.add(int(part) - 1)
    return sorted(p for p in pages if 0 <= p < total)


def raster_mode(src: Path, dst: Path, args) -> list:
    import cv2
    import numpy as np
    from PIL import Image
    sys.path.insert(0, str(HERE))
    import remove_watermark as rw

    reader = PdfReader(str(src))
    indices = parse_pages(args.pages, len(reader.pages))
    imgs = render_pages(src, args.dpi, indices)
    previews = []
    cleaned = {}
    for i, pil in imgs.items():
        bgr = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
        mask = rw.finish_mask(rw.build_mask(bgr, args), args.dilate)
        cov = 100 * np.count_nonzero(mask) / mask.size
        out = rw.inpaint(bgr, mask, args.radius, args.method) if cov else bgr
        print(f"  {i + 1}쪽: 지운 면적 {cov:.2f}%")
        cleaned[i] = Image.fromarray(cv2.cvtColor(out, cv2.COLOR_BGR2RGB))
        previews.append((i, bgr, mask, out))

    writer = PdfWriter()
    for i, page in enumerate(reader.pages):
        if i in cleaned:
            buf = io.BytesIO()
            cleaned[i].save(buf, format="PDF", resolution=args.dpi)
            new_page = PdfReader(buf).pages[0]
            new_page.scale_to(float(page.mediabox.width), float(page.mediabox.height))
            writer.add_page(new_page)
        else:
            writer.add_page(page)
    with open(dst, "wb") as f:
        writer.write(f)
    return previews


# ---------------------------------------------------------------- 미리보기

def write_preview(src: Path, dst: Path, preview_path: Path, page_no: int = 0):
    from PIL import Image
    before = render_pages(src, 80, [page_no]).get(page_no)
    after = render_pages(dst, 80, [page_no]).get(page_no)
    if before is None or after is None:
        return
    w = before.width + after.width + 10
    canvas = Image.new("RGB", (w, max(before.height, after.height)), "white")
    canvas.paste(before, (0, 0))
    canvas.paste(after, (before.width + 10, 0))
    preview_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(preview_path)
    print(f"  비교 이미지(왼쪽 원본 | 오른쪽 결과): {preview_path}")


# ---------------------------------------------------------------- main

def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="PDF 워터마크 제거",
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    p.add_argument("input", help="PDF 파일")
    p.add_argument("-o", "--output", help="결과 파일 (기본: 원본이름_clean.pdf)")
    p.add_argument("--text", action="append", default=[], metavar="문구", help="지울 워터마크 문구 (여러 번 가능)")
    p.add_argument("--no-heuristic", action="store_true", help="기울어진/반투명 큰 글씨 자동 제거 끄기")
    p.add_argument("--list", action="store_true", help="지우지 않고 무엇이 지워질지·반복되는 글씨만 보여줌")
    p.add_argument("--preview", nargs="?", const="auto", metavar="PNG", help="원본|결과 첫 쪽 비교 이미지 저장")
    p.add_argument("--preview-page", type=int, default=1, help="비교 이미지에 쓸 쪽 번호 (기본 1)")
    p.add_argument("--password", help="암호가 걸린 PDF 의 암호")
    # 래스터 모드
    g = p.add_argument_group("스캔본(--raster) 옵션: remove_watermark.py 와 같음")
    g.add_argument("--raster", action="store_true", help="페이지를 이미지로 바꿔 지움 (글자 선택 불가가 됨)")
    g.add_argument("--pages", help="래스터 처리할 쪽 (예: 1,3-5). 기본 전체")
    g.add_argument("--dpi", type=int, default=200)
    g.add_argument("--box", action="append")
    g.add_argument("--mask")
    g.add_argument("--auto", action="store_true")
    g.add_argument("--region", default="all")
    g.add_argument("--color", default="light", choices=["light", "dark", "any"])
    g.add_argument("--threshold", type=int)
    g.add_argument("--dilate", type=int, default=3)
    g.add_argument("--radius", type=int, default=5)
    g.add_argument("--method", default="telea", choices=["telea", "ns"])
    args = p.parse_args(argv)

    src = Path(args.input)
    if not src.is_file():
        p.error(f"파일이 없습니다: {src}")
    dst = Path(args.output) if args.output else src.with_name(src.stem + "_clean.pdf")
    preview = None
    if args.preview:
        preview = dst.with_name(dst.stem + "_preview.png") if args.preview == "auto" else Path(args.preview)

    if args.raster:
        if not (args.box or args.mask or args.auto):
            p.error("--raster 에는 --box, --mask, --auto 중 하나 이상이 필요합니다")
        print(f"[래스터] {src.name}")
        raster_mode(src, dst, args)
        print(f"[완료] → {dst}  (처리한 쪽은 이미지가 되어 글자 선택이 안 됩니다)")
        if preview:
            write_preview(src, dst, preview, args.preview_page - 1)
        return 0

    reader = PdfReader(str(src))
    if reader.is_encrypted:
        if reader.decrypt(args.password or "") == 0:
            p.error("암호가 걸린 PDF 입니다. --password 로 암호를 알려주세요")
    writer = PdfWriter(clone_from=reader)
    cleaner = Cleaner(writer, args.text, heuristic=not args.no_heuristic, dry=args.list)
    for i, page in enumerate(writer.pages):
        cleaner.clean_page(i, page)

    if args.list:
        print(f"[미리 보기] {src.name} ({len(writer.pages)}쪽) — 실제로는 바꾸지 않았습니다")
        for line in cleaner.log or ["지울 워터마크를 찾지 못했습니다"]:
            print("  - " + line)
        n = len(writer.pages)
        repeated = [(t, ang, c) for (t, ang), c in cleaner.text_seen.most_common(15)
                    if c >= 2 and len(norm(t)) >= 2]
        if repeated:
            print("  여러 번 반복되는 글씨 (워터마크 후보, --text 로 지정 가능):")
            for t, ang, c in repeated:
                tag = f", 기울기 {ang}°" if ang not in (0, 90, -90, 180, -180) else ""
                print(f"    {c:>3}회{tag}: {t[:60]!r}")
        return 0

    if not cleaner.log:
        print(f"[변화 없음] {src.name}: 워터마크를 찾지 못했습니다.")
        print("  --list 로 반복되는 글씨를 확인해 --text 로 지정하거나, 스캔본이면 --raster 를 쓰세요.")
        return 1
    with open(dst, "wb") as f:
        writer.write(f)
    print(f"[완료] {src.name} → {dst}")
    for line in Counter(cleaner.log).items():
        msg, c = line
        print(f"  - {msg}" + (f" ×{c}" if c > 1 else ""))
    if preview:
        write_preview(src, dst, preview, args.preview_page - 1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
