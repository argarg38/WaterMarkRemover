---
name: watermark-remover
description: 이미지·PDF·Word(docx)·PowerPoint(pptx)·Excel(xlsx) 문서에서 워터마크(CONFIDENTIAL, DRAFT, 대외비, SAMPLE, 로고, 배경 그림, 날짜 도장 등)를 지울 때 사용. 사용자가 "워터마크 지워줘", "로고/도장/대외비 표시 없애줘", "remove watermark"라고 하거나, Claude가 받은 문서를 읽고·요약하고·고치는 중에 워터마크 글자가 추출된 텍스트에 섞이거나 내용을 가려 작업을 방해할 때 먼저 이 스킬로 정리한 뒤 이어서 작업한다. .doc .ppt .xls .hwp 등 구형 형식은 변환 후 처리한다.
---

# Watermark Remover

파일 형식에 따라 지우는 방식이 다르다. 진입점은 하나다: `scripts/remove_watermark.py` (이 SKILL.md가 있는 폴더 기준).
확장자를 보고 알아서 PDF용·오피스용·이미지용 처리로 넘긴다.

| 형식 | 방식 | 결과 |
|---|---|---|
| docx / pptx / xlsx | 문서 속 워터마크 개체(도형·WordArt·배경 그림·머리글 그림)만 삭제 | 본문은 그대로 편집 가능 |
| PDF (디지털 원본) | 워터마크 주석·워터마크 표시 영역·기울어진/반투명 큰 글씨·지정 문구를 삭제 | 글자 선택·검색 유지 |
| PDF (스캔본) / 이미지 | 워터마크 부분을 주변 픽셀로 메움 (OpenCV inpainting) | 그림이므로 흔적이 조금 남을 수 있음 |
| .doc .ppt .xls .rtf .odt .hwp | LibreOffice로 docx/pptx/xlsx 변환 후 위 방식 | 결과는 변환된 형식으로 저장 |

## 사용 범위

사용자가 만들었거나 쓸 권리가 있는 파일에 쓴다(내 보고서의 DRAFT 표시, 사내 문서의 대외비 배경, 내 사진의 날짜 도장, 분석을 방해하는 워터마크 글자 등).
스톡 이미지·유료 자료처럼 다른 사람 저작물의 워터마크를 지워 라이선스 없이 쓰려는 목적이 분명하면 그 목적으로는 돕지 말고, 원본 구매나 허락을 받는 방법을 안내한다.

## 준비

```bash
pip install opencv-python-headless numpy pypdf lxml pillow pypdfium2   # 이미 있는 건 건너뜀
```

claude.ai 채팅에서는 올린 파일이 보통 `/mnt/user-data/uploads/`에 있고, 결과는 `/mnt/user-data/outputs/`에 저장해야 사용자가 내려받을 수 있다.
원본은 절대 덮어쓰지 말고 `-o`로 새 파일에 저장한다(기본값도 `원본이름_clean.확장자`).

```bash
S=<이 스킬 폴더>/scripts/remove_watermark.py
```

## 작업 순서

### 1) 먼저 살펴보기: `--list`

문서는 항상 `--list`부터 실행한다. 아무것도 바꾸지 않고, 자동으로 지울 항목과 워터마크 후보(반복되는 글씨, 머리글/바닥글·슬라이드 마스터 내용)를 보여준다.

```bash
python $S report.pdf --list
python $S report.docx --list
```

PDF는 첫 쪽을 이미지로 렌더링해 직접 눈으로도 확인한다(`--preview`가 이걸 대신 만들어 준다).

### 2) 지우기

```bash
# 자동 탐지만으로 충분한 경우 (Word 워터마크 기능, PDF의 워터마크 개체, 기울어진 큰 글씨 등)
python $S report.docx -o /mnt/user-data/outputs/report_clean.docx
python $S report.pdf --preview

# 후보 목록에서 본 문구를 지정 (여러 번 가능, 대소문자·띄어쓰기 무시)
python $S report.pdf --text "대외비" --text "CONFIDENTIAL" --preview
python $S deck.pptx --text DRAFT
python $S sheet.xlsx --text "Internal Use Only"

# docx 머리글에 '텍스트 뒤'로 깔린 로고/그림까지
python $S report.docx --behind-images

# 스캔본 PDF: 이미지처럼 처리 (이미지 옵션 그대로 사용)
python $S scan.pdf --raster --auto --region center --preview
python $S scan.pdf --raster --box 30%,40%,40%,20% --pages 1-3

# 이미지
python $S photo.jpg --auto --region br --preview
python $S photo.jpg --box 75%,88%,24%,10%
python $S photos/ -o photos_clean/ --shared --preview     # 여러 장의 공통 워터마크
```

### 3) 확인하기

- 출력 로그에 무엇을 지웠는지 나온다. 본문 문장이 지워진 항목으로 나오면 `--text`를 더 구체적으로 바꾸거나 `--no-heuristic`(PDF 자동 추정 끄기)을 쓴다.
- PDF/이미지는 `--preview`로 만든 비교 이미지(원본 | 결과)를 직접 열어 본다.
- 오피스 문서는 `python -c`로 다시 열어 본문이 그대로인지 확인한다(예: python-docx로 문단 수, pypdf로 `extract_text()`).
- "변화 없음"이 나오면: `--list` 후보에서 `--text` 지정 → 그래도 안 되면 PDF는 `--raster`로 처리.

### 4) 이어서 작업하기

워터마크 때문에 문서 읽기·요약·번역이 방해받던 경우라면, 정리된 `_clean` 파일로 원래 작업을 이어간다. 사용자에게는 무엇을 지웠는지 한두 줄로 알려준다.

## 옵션 요약

| 옵션 | 대상 | 설명 |
|---|---|---|
| `--list` | 문서 | 바꾸지 않고 후보만 출력 |
| `--text 문구` | 문서 | 그 문구로 된 글자/도형/머리글 문구 삭제 |
| `--no-heuristic` | PDF | 기울어진·반투명 큰 글씨와 반투명 큰 도형 자동 삭제 끄기 |
| `--raster`, `--pages`, `--dpi` | PDF | 스캔본을 이미지 방식으로 처리 |
| `--behind-images` | docx | 머리글의 텍스트 뒤 그림 삭제 |
| `--password` | PDF | 암호 걸린 PDF |
| `--preview` | PDF·이미지 | 비교 이미지 저장 |
| `--box`, `--auto`, `--region`, `--color`, `--shared`, `--mask`, `--dilate`, `--threshold` | 이미지·스캔 PDF | 이미지 방식 영역 지정/조정 |

자세한 도움말: `python scripts/remove_pdf_watermark.py -h`, `python scripts/remove_office_watermark.py -h`, `python scripts/remove_watermark.py -h`

## 한계

- PDF는 만든 프로그램마다 워터마크를 넣는 방식이 달라 자동 탐지가 놓칠 수 있다. `--list` → `--text` → `--raster` 순서로 시도한다.
- PDF `--text`는 그 문구를 그리는 글자 조각을 지운다. 본문 문장 안에 같은 단어가 있으면 그 조각도 지워질 수 있으니 로그를 꼭 확인한다.
- 글꼴 정보가 없는 PDF(글자 인코딩을 알 수 없음)는 문구 매칭이 안 될 수 있다. 이때는 `--raster`.
- 이미지/스캔본 방식은 작은 워터마크에 잘 맞고, 페이지 전체를 덮는 반복 워터마크는 흔적이 남는다. 그럴 땐 한계를 솔직히 말한다.
- .hwp 변환은 LibreOffice 버전에 따라 안 될 수 있다. 그때는 한글에서 docx나 PDF로 저장해 달라고 안내한다.
