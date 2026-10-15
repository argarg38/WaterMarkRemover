#!/usr/bin/env python3
"""텍스트 파일의 숨은 문자 정돈 — 원본은 그대로 두고 새 파일에만 저장한다.

기본으로 하는 일
  - 보이지 않는 문자(제로폭)·방향 제어 문자·유니코드 태그 문자·제어 문자·BOM 삭제
  - 이모지/한자 외의 변형 선택자 삭제 (이모지 결합 문자는 유지)
  - 특수 공백(NBSP, 전각 공백 등) → 일반 공백
  - 유니코드 NFC 정규화 (분리된 한글 자모 합치기)
선택
  --fix-homoglyphs       라틴 단어 안에 섞인 키릴/그리스 글자를 라틴 글자로 바꿈
  --strip-front-matter   맨 앞 YAML front matter 삭제
  --strip-comments       HTML 주석(<!-- -->)과 마크다운 주석([//]: # ...) 삭제
  --keep-spaces          특수 공백을 바꾸지 않음
  --keep-private-use     사용자 정의 영역 문자를 지우지 않음

줄바꿈(CRLF/LF)과 그 밖의 내용은 바꾸지 않는다.
통계적 텍스트 워터마크(단어 선택 패턴)는 이 도구로 지울 수 없고, 지워졌는지 확인할 수도 없다.

예시
  python clean_text.py draft.md                      # → draft.cleaned.md
  python clean_text.py draft.md -o out/draft.cleaned.md --strip-comments
"""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from inspect_file import CATEGORIES, CONFUSABLES, classify, homoglyph_words, read_text  # noqa: E402

REMOVE = {"zero_width", "bidi", "tags", "variation", "control", "bom", "private_use"}


def clean(text: str, args) -> tuple[str, Counter]:
    stats: Counter = Counter()
    remove = set(REMOVE)
    if args.keep_private_use:
        remove.discard("private_use")

    out = []
    for i, ch in enumerate(text):
        key = classify(text, i)
        if key in remove:
            stats[key] += 1
            continue
        if key == "odd_space" and not args.keep_spaces:
            stats[key] += 1
            out.append(" ")
            continue
        out.append(ch)
    text = "".join(out)

    if args.fix_homoglyphs:
        chars = list(text)
        for idx, word, _ in list(homoglyph_words(text)):
            for j, ch in enumerate(word):
                if ch in CONFUSABLES:
                    chars[idx + j] = CONFUSABLES[ch]
                    stats["homoglyph"] += 1
        text = "".join(chars)

    if args.strip_front_matter:
        new = re.sub(r"\A---\s*\n.*?\n(---|\.\.\.)\s*(\n|$)", "", text, count=1, flags=re.S)
        if new != text:
            stats["front matter"] += 1
            text = new
    if args.strip_comments:
        text, n1 = re.subn(r"<!--.*?-->", "", text, flags=re.S)
        text, n2 = re.subn(r"^\[(?://|comment|_)\]:\s*#.*(\r?\n)?", "", text, flags=re.M)
        if n1 + n2:
            stats["주석"] += n1 + n2

    nfc = unicodedata.normalize("NFC", text)
    if nfc != text:
        stats["not_nfc"] += max(1, len(text) - len(nfc))
        text = nfc
    return text, stats


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="텍스트 숨은 문자 정돈 (원본은 바꾸지 않음)",
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    p.add_argument("input")
    p.add_argument("-o", "--output", help="결과 파일 (기본: 이름.cleaned.확장자)")
    p.add_argument("--fix-homoglyphs", action="store_true")
    p.add_argument("--strip-front-matter", action="store_true")
    p.add_argument("--strip-comments", action="store_true")
    p.add_argument("--keep-spaces", action="store_true")
    p.add_argument("--keep-private-use", action="store_true")
    p.add_argument("--force", action="store_true", help="결과 파일이 이미 있으면 덮어쓰기 (원본 덮어쓰기는 항상 금지)")
    args = p.parse_args(argv)

    src = Path(args.input)
    if not src.is_file():
        p.error(f"파일이 없습니다: {src}")
    dst = Path(args.output) if args.output else src.with_name(f"{src.stem}.cleaned{src.suffix}")
    if dst.resolve() == src.resolve():
        p.error("결과 파일이 원본과 같습니다. 원본은 수정하지 않습니다. 다른 -o 경로를 지정하세요")
    if dst.exists() and not args.force:
        p.error(f"{dst} 가 이미 있습니다. 덮어쓰려면 --force")

    text, enc = read_text(src)
    cleaned, stats = clean(text, args)
    dst.parent.mkdir(parents=True, exist_ok=True)
    with open(dst, "w", encoding="utf-8", newline="") as f:
        f.write(cleaned)

    print(f"[완료] {src} → {dst}  (원본은 바뀌지 않음)")
    if enc != "utf-8":
        print(f"  - 인코딩 {enc} → utf-8 로 저장")
    if not stats:
        print("  - 바꾼 것 없음 (내용은 원본과 같음)")
    for key, n in stats.items():
        label = CATEGORIES[key][0] if key in CATEGORIES else key
        verb = {"odd_space": "일반 공백으로 바꿈", "homoglyph": "라틴 글자로 바꿈",
                "not_nfc": "자 합침(NFC)"}.get(key, "삭제")
        print(f"  - {label}: {n}{'' if key == 'not_nfc' else '건 '}{verb}")
    kept = []
    if not args.fix_homoglyphs and any(True for _ in homoglyph_words(cleaned)):
        kept.append("다른 문자 체계가 섞인 단어 (--fix-homoglyphs)")
    if not args.strip_front_matter and re.match(r"\A---\s*\n", cleaned):
        kept.append("YAML front matter (--strip-front-matter)")
    if not args.strip_comments and re.search(r"<!--.*?-->|^\[(?://|comment|_)\]:\s*#", cleaned, re.S | re.M):
        kept.append("주석 (--strip-comments)")
    if kept:
        print("  - 일부러 남긴 것 (내용 판단이 필요해 기본값으로는 안 지움): " + ", ".join(kept))
    print(f"  - 글자 수: {len(text):,} → {len(cleaned):,}")
    print("  ※ 통계적 텍스트 워터마크는 이 도구로 지우거나 확인할 수 없습니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
