#!/usr/bin/env python3
"""워터마크 제거 도구 — 이미지는 여기서 직접, 문서는 전용 스크립트로 넘긴다.

  .pdf                          → remove_pdf_watermark.py
  .docx .pptx .xlsx (.doc 등)   → remove_office_watermark.py
  그 밖의 이미지                 → 아래 OpenCV inpainting

워터마크 위치를 마스크로 만든 뒤, 그 부분을 주변 픽셀로 채워 지운다.
마스크를 만드는 방법은 네 가지다.

  --box x,y,w,h     직접 영역 지정 (픽셀 또는 %, 여러 번 사용 가능)
  --mask FILE       흰색 = 지울 곳인 마스크 이미지
  --auto            밝은/어두운 반투명 글씨를 자동 탐지 (--region 으로 범위 제한 권장)
  --shared          폴더 안 여러 장에 같은 자리 같은 워터마크가 있을 때 공통 부분을 찾아냄

예시
  python remove_watermark.py photo.jpg --box 80%,90%,20%,10%
  python remove_watermark.py photo.jpg --auto --region br --preview preview.png
  python remove_watermark.py photos/ -o cleaned/ --shared
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    import cv2
    import numpy as np
except ImportError:  # pragma: no cover
    sys.exit("필요한 패키지가 없습니다: pip install opencv-python-headless numpy")

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}

# 영역 이름 → (x0, y0, x1, y1) 비율
REGIONS = {
    "all": (0.0, 0.0, 1.0, 1.0),
    "tl": (0.0, 0.0, 0.4, 0.3),
    "tr": (0.6, 0.0, 1.0, 0.3),
    "bl": (0.0, 0.7, 0.4, 1.0),
    "br": (0.6, 0.7, 1.0, 1.0),
    "top": (0.0, 0.0, 1.0, 0.3),
    "bottom": (0.0, 0.7, 1.0, 1.0),
    "center": (0.2, 0.3, 0.8, 0.7),
}


# ---------------------------------------------------------------- 입출력

def read_image(path: Path) -> np.ndarray:
    # cv2.imread 는 한글 경로를 못 읽는 환경이 있어 바이트로 읽는다
    data = np.fromfile(str(path), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise ValueError(f"이미지를 읽을 수 없습니다: {path}")
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    return img


def write_image(path: Path, img: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ext = path.suffix.lower() or ".png"
    ok, buf = cv2.imencode(ext, img)
    if not ok:
        raise ValueError(f"이미지를 저장할 수 없습니다: {path}")
    buf.tofile(str(path))


# ---------------------------------------------------------------- 마스크 만들기

def parse_box(spec: str, w: int, h: int) -> tuple[int, int, int, int]:
    parts = [p.strip() for p in spec.split(",")]
    if len(parts) != 4:
        raise ValueError(f"--box 는 x,y,w,h 형식이어야 합니다: {spec}")

    def conv(v: str, total: int) -> int:
        return round(float(v[:-1]) / 100 * total) if v.endswith("%") else int(float(v))

    x, y = conv(parts[0], w), conv(parts[1], h)
    bw, bh = conv(parts[2], w), conv(parts[3], h)
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(w, x + bw), min(h, y + bh)
    if x1 <= x0 or y1 <= y0:
        raise ValueError(f"--box 영역이 이미지 밖입니다: {spec}")
    return x0, y0, x1, y1


def region_rect(name: str, w: int, h: int) -> tuple[int, int, int, int]:
    fx0, fy0, fx1, fy1 = REGIONS[name]
    return int(fx0 * w), int(fy0 * h), int(fx1 * w), int(fy1 * h)


def mask_from_boxes(specs: list[str], shape) -> np.ndarray:
    h, w = shape[:2]
    mask = np.zeros((h, w), np.uint8)
    for spec in specs:
        x0, y0, x1, y1 = parse_box(spec, w, h)
        mask[y0:y1, x0:x1] = 255
    return mask


def load_mask(path: Path, shape) -> np.ndarray:
    m = read_image(path)
    m = cv2.cvtColor(m[:, :, :3], cv2.COLOR_BGR2GRAY)
    if m.shape != shape[:2]:
        m = cv2.resize(m, (shape[1], shape[0]), interpolation=cv2.INTER_NEAREST)
    return np.where(m > 127, 255, 0).astype(np.uint8)


def remove_small(mask: np.ndarray, min_area: int) -> np.ndarray:
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    keep = np.zeros_like(mask)
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] >= min_area:
            keep[labels == i] = 255
    return keep


def auto_mask(img: np.ndarray, region: str, color: str, threshold: int | None) -> np.ndarray:
    """반투명 글씨/로고 형태의 워터마크를 형태학적 연산으로 찾는다."""
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img[:, :, :3], cv2.COLOR_BGR2GRAY)
    k = max(9, (min(h, w) // 40) | 1)  # 글자 굵기보다 큰 커널
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))

    responses = []
    if color in ("light", "any"):
        responses.append(cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, kernel))
    if color in ("dark", "any"):
        responses.append(cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT, kernel))
    resp = np.max(np.stack(responses), axis=0)

    x0, y0, x1, y1 = region_rect(region, w, h)
    roi = resp[y0:y1, x0:x1]
    if threshold is None:
        t, _ = cv2.threshold(roi, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        threshold = max(int(t), 18)
    mask = np.zeros((h, w), np.uint8)
    mask[y0:y1, x0:x1] = np.where(roi >= threshold, 255, 0).astype(np.uint8)

    # 워터마크는 대개 채도가 낮다(흰/회/검). 색이 진한 픽셀은 제외
    hsv = cv2.cvtColor(img[:, :, :3], cv2.COLOR_BGR2HSV)
    mask[hsv[:, :, 1] > 110] = 0

    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    return remove_small(mask, max(6, (h * w) // 50000))


def shared_mask(images: list[np.ndarray], threshold: float | None) -> np.ndarray:
    """같은 크기 이미지 여러 장에서 항상 같은 자리에 있는 윤곽(=워터마크)을 찾는다."""
    mags = []
    for img in images:
        gray = cv2.cvtColor(img[:, :, :3], cv2.COLOR_BGR2GRAY).astype(np.float32)
        gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
        mags.append(cv2.magnitude(gx, gy))
    med = np.median(np.stack(mags), axis=0)
    med = cv2.normalize(med, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    if threshold is None:
        t, _ = cv2.threshold(med, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        threshold = t
    mask = np.where(med >= threshold, 255, 0).astype(np.uint8)
    # 윤곽선 사이(글자 내부)까지 채우기
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    h, w = mask.shape
    return remove_small(mask, max(10, (h * w) // 20000))


# ---------------------------------------------------------------- 지우기

def inpaint(img: np.ndarray, mask: np.ndarray, radius: int, method: str) -> np.ndarray:
    flag = cv2.INPAINT_TELEA if method == "telea" else cv2.INPAINT_NS
    alpha = img[:, :, 3] if img.shape[2] == 4 else None
    out = cv2.inpaint(img[:, :, :3], mask, radius, flag)
    if alpha is not None:
        out = np.dstack([out, alpha])
    return out


def make_preview(img: np.ndarray, mask: np.ndarray, out: np.ndarray) -> np.ndarray:
    base = img[:, :, :3]
    overlay = base.copy()
    overlay[mask > 0] = (0, 0, 255)
    overlay = cv2.addWeighted(base, 0.5, overlay, 0.5, 0)
    strip = np.hstack([base, overlay, out[:, :, :3]])
    max_w = 2400
    if strip.shape[1] > max_w:
        s = max_w / strip.shape[1]
        strip = cv2.resize(strip, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    return strip


def build_mask(img: np.ndarray, args) -> np.ndarray:
    h, w = img.shape[:2]
    mask = np.zeros((h, w), np.uint8)
    if args.box:
        mask |= mask_from_boxes(args.box, img.shape)
    if args.mask:
        mask |= load_mask(Path(args.mask), img.shape)
    if args.auto:
        mask |= auto_mask(img, args.region, args.color, args.threshold)
    return mask


def finish_mask(mask: np.ndarray, dilate: int) -> np.ndarray:
    if dilate > 0:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * dilate + 1, 2 * dilate + 1))
        mask = cv2.dilate(mask, k)
    return mask


def process(img: np.ndarray, mask: np.ndarray, src: Path, dst: Path, args) -> None:
    mask = finish_mask(mask, args.dilate)
    coverage = 100 * np.count_nonzero(mask) / mask.size
    if coverage == 0:
        print(f"[건너뜀] {src.name}: 워터마크를 찾지 못했습니다 (--box 로 위치를 직접 지정해 보세요)")
        return
    out = inpaint(img, mask, args.radius, args.method)
    write_image(dst, out)
    note = "  ⚠ 마스크가 넓습니다. 결과가 뭉개졌다면 --region/--box 로 범위를 좁히세요" if coverage > 15 else ""
    print(f"[완료] {src.name} → {dst}  (지운 면적 {coverage:.2f}%){note}")
    if args.save_mask:
        write_image(sibling(dst, args.save_mask, "_mask", ".png"), mask)
    if args.preview:
        write_image(sibling(dst, args.preview, "_preview", ".jpg"), make_preview(img, mask, out))


def sibling(dst: Path, opt: str, suffix: str, ext: str) -> Path:
    """단일 파일이면 지정 경로 그대로, 배치면 결과 파일 옆에 접미사를 붙인다."""
    if opt != "auto":
        return Path(opt)
    return dst.with_name(dst.stem + suffix + ext)


# ---------------------------------------------------------------- main

PDF_EXTS = {".pdf"}
OFFICE_EXTS = {".docx", ".docm", ".dotx", ".dotm", ".pptx", ".pptm", ".potx", ".xlsx", ".xlsm", ".xltx",
               ".doc", ".dot", ".rtf", ".odt", ".hwp", ".ppt", ".odp", ".xls", ".ods"}


def route_documents(argv) -> int | None:
    """입력이 문서면 PDF/오피스 전용 스크립트로 넘긴다."""
    args = sys.argv[1:] if argv is None else list(argv)
    first = next((a for a in args if not a.startswith("-")), "")
    ext = Path(first).suffix.lower()
    if ext not in PDF_EXTS | OFFICE_EXTS:
        return None
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    if ext in PDF_EXTS:
        import remove_pdf_watermark as mod
    else:
        import remove_office_watermark as mod
    return mod.main(args)


def main(argv=None) -> int:
    routed = route_documents(argv)
    if routed is not None:
        return routed
    p = argparse.ArgumentParser(description="이미지 워터마크 제거 (OpenCV inpainting)",
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    p.add_argument("input", help="이미지 파일 또는 폴더")
    p.add_argument("-o", "--output", help="결과 파일/폴더 (기본: 원본이름_clean)")
    p.add_argument("--box", action="append", metavar="X,Y,W,H", help="지울 영역. 픽셀 또는 %% (여러 번 가능)")
    p.add_argument("--mask", help="마스크 이미지 (흰색 = 지울 곳)")
    p.add_argument("--auto", action="store_true", help="워터마크 자동 탐지")
    p.add_argument("--region", choices=REGIONS, default="all", help="--auto 탐색 범위 (기본 all)")
    p.add_argument("--color", choices=["light", "dark", "any"], default="light", help="워터마크 밝기 (기본 light)")
    p.add_argument("--threshold", type=int, help="자동 탐지 민감도 (낮을수록 많이 잡음)")
    p.add_argument("--shared", action="store_true", help="폴더 내 여러 장의 공통 워터마크 탐지")
    p.add_argument("--dilate", type=int, default=3, help="마스크 확장 픽셀 (기본 3)")
    p.add_argument("--radius", type=int, default=5, help="inpaint 반경 (기본 5)")
    p.add_argument("--method", choices=["telea", "ns"], default="telea")
    p.add_argument("--save-mask", nargs="?", const="auto", metavar="PATH", help="사용한 마스크도 저장")
    p.add_argument("--preview", nargs="?", const="auto", metavar="PATH", help="원본|마스크|결과 비교 이미지 저장")
    args = p.parse_args(argv)

    src = Path(args.input)
    if not src.exists():
        p.error(f"입력이 없습니다: {src}")
    if not (args.box or args.mask or args.auto or args.shared):
        p.error("--box, --mask, --auto, --shared 중 하나 이상 지정하세요")

    if src.is_file():
        if args.shared:
            p.error("--shared 는 폴더 입력에서만 쓸 수 있습니다")
        dst = Path(args.output) if args.output else src.with_name(src.stem + "_clean" + src.suffix)
        img = read_image(src)
        process(img, build_mask(img, args), src, dst, args)
        return 0

    files = sorted(f for f in src.iterdir() if f.suffix.lower() in IMAGE_EXTS)
    if not files:
        p.error(f"폴더에 이미지가 없습니다: {src}")
    out_dir = Path(args.output) if args.output else src.with_name(src.name + "_clean")
    if args.save_mask and args.save_mask != "auto" or args.preview and args.preview != "auto":
        p.error("폴더 입력에서는 --save-mask/--preview 에 경로 없이 플래그만 쓰세요")

    images = {f: read_image(f) for f in files}
    shared = {}
    if args.shared:
        by_size: dict[tuple, list[Path]] = {}
        for f, img in images.items():
            by_size.setdefault(img.shape[:2], []).append(f)
        for size, group in by_size.items():
            if len(group) < 3:
                print(f"[경고] {size[1]}x{size[0]} 크기 이미지가 {len(group)}장뿐이라 --shared 탐지를 건너뜁니다 (3장 이상 필요)")
                continue
            m = shared_mask([images[f] for f in group], args.threshold)
            for f in group:
                shared[f] = m

    for f, img in images.items():
        mask = build_mask(img, args)
        if f in shared:
            mask |= shared[f]
        process(img, mask, f, out_dir / f.name, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
