---
name: watermark-remover
description: 이미지·PDF·Word(docx)·PowerPoint(pptx)·Excel(xlsx) 문서의 눈에 보이는 워터마크(CONFIDENTIAL, DRAFT, 대외비, SAMPLE, 로고, 배경 그림, 날짜 도장 등)를 지우거나, 텍스트(.md .txt 등)와 문서의 숨은 문자(제로폭·방향 제어·태그 문자·동형 문자)·메타데이터를 검사하고 새 파일로 정돈할 때 사용. 사용자가 "워터마크 지워줘", "로고/도장/대외비 표시 없애줘", "숨은 문자 검사해줘", "remove watermark"라고 하거나, Claude가 받은 문서를 읽고·요약하고·고치는 중에 워터마크 글자나 숨은 문자가 섞여 작업을 방해할 때 먼저 이 스킬로 정리한 뒤 이어서 작업한다. .doc .ppt .xls .hwp 등 구형 형식은 변환 후 처리한다.
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
| 텍스트 (.md .txt .html .csv …) | 숨은 문자·메타데이터 검사(`inspect_file.py`) 후 새 파일로 정돈(`clean_text.py`) | 원본은 그대로, `이름.cleaned.확장자` |

## 작업 원칙 (모든 형식 공통, 사용자가 따로 말하지 않아도 지킨다)

1. **실행할 명령어를 먼저 보여준다.** 실제로 실행하기 전에 쓸 명령어를 코드 블록으로 보여주고, 그다음에 실행한다.
2. **먼저 검사만 한다.** 바꾸기 전에 읽기 전용 검사를 먼저 돌리고(`inspect_file.py`, 문서는 `--list`), 발견 항목을 **종류별로** 무엇인지·왜 문제인지·어디 있는지 설명한다.
3. **원본은 절대 수정하지 않는다.** 결과는 항상 새 파일로 저장한다. 텍스트는 `이름.cleaned.확장자`(예: `draft.md` → `draft.cleaned.md`), 문서·이미지는 `이름_clean.확장자`. 스크립트도 원본과 같은 경로로는 저장을 거부한다.
4. **정돈 후 같은 검사 도구로 다시 검사하고 전후를 비교한다.** `inspect_file.py 원본 --compare 결과`로 표를 보여준다. 보이는 워터마크는 `--list`를 결과 파일에 다시 실행하거나 `--preview`로 비교한다.
5. **세 가지를 구분해서 설명한다.**
   - 눈에 보이는 워터마크: 글자·로고·도장·배경 그림
   - 숨은 문자·메타데이터: 제로폭 문자, 방향 제어 문자, 태그 문자, 동형 문자, 문서 속성, 주석. 이건 검사로 확인되고 지운 것도 재검사로 확인된다.
   - 통계적 텍스트 워터마크: AI가 글을 만들 때 단어 선택 확률에 심는 패턴. 이건 이 도구들로 탐지도, 제거도, 제거 확인도 할 수 없다.
6. **통계적 워터마크가 없다거나 제거됐다고 단정하지 않는다.** "숨은 문자 0건"은 숨은 문자가 없다는 뜻일 뿐이다. 이 스킬은 통계적 워터마크를 피하려고 글을 바꿔 쓰는(패러프레이즈) 작업을 하지 않는다.
7. 내용 판단이 필요한 항목(동형 문자, front matter, 주석, 문서 속성)은 기본값으로 지우지 않고, 무엇이 남았는지 알려준 뒤 사용자가 원하면 옵션으로 지운다.

## 사용 범위

사용자가 만들었거나 쓸 권리가 있는 파일에 쓴다(내 보고서의 DRAFT 표시, 사내 문서의 대외비 배경, 내 사진의 날짜 도장, 분석을 방해하는 워터마크 글자 등).
스톡 이미지·유료 자료처럼 다른 사람 저작물의 워터마크를 지워 라이선스 없이 쓰려는 목적이 분명하면 그 목적으로는 돕지 말고, 원본 구매나 허락을 받는 방법을 안내한다.

## 준비

```bash
pip install opencv-python-headless numpy pypdf lxml pillow pypdfium2   # 이미 있는 건 건너뜀 (텍스트 검사만이면 필요 없음)
```

claude.ai 채팅에서는 올린 파일이 보통 `/mnt/user-data/uploads/`에 있고, 결과는 `/mnt/user-data/outputs/`에 저장해야 사용자가 내려받을 수 있다.
원본은 절대 덮어쓰지 말고 `-o`로 새 파일에 저장한다(기본값도 `원본이름_clean.확장자`).

```bash
S=<이 스킬 폴더>/scripts/remove_watermark.py
```

## 텍스트 파일: 숨은 문자·메타데이터 검사와 정돈

```bash
I=<이 스킬 폴더>/scripts/inspect_file.py
C=<이 스킬 폴더>/scripts/clean_text.py
```

예: "draft.md 검사해줘" → 아래 순서를 그대로 따른다.

**① 명령어 먼저 보여주기**: 아래 ②~④에서 실행할 명령어 전체를 먼저 보여준다.

**② 검사만 하기 (읽기 전용)**
```bash
python $I draft.md
```
출력의 `[1] 숨은 문자`, `[2] 메타데이터`, `[3] 통계적 텍스트 워터마크`를 종류별로 풀어서 설명한다.
태그 문자가 있으면 해독된 숨은 글자도 알려준다.

**③ 새 파일로 정돈**
```bash
python $C draft.md -o draft.cleaned.md
```
기본으로 지우거나 바꾸는 것은 제로폭·방향 제어·태그·제어 문자, 이모지가 아닌 곳의 변형 선택자, BOM, 특수 공백(일반 공백으로), NFC 정규화다.
사용자가 원할 때만 쓰는 옵션: `--fix-homoglyphs`(동형 문자), `--strip-front-matter`, `--strip-comments`.
이모지 결합 문자(👨‍👩‍👧)와 이모지·한자 뒤 변형 선택자, 줄바꿈 방식은 그대로 둔다.

**④ 같은 도구로 재검사하고 전후 비교**
```bash
python $I draft.cleaned.md
python $I draft.md --compare draft.cleaned.md
```
표의 `제거됨 / 그대로 / 새로 생김`을 설명하고, 남은 항목은 왜 남겼는지 말한다.
마지막에 통계적 워터마크는 확인할 수 없다는 점을 다시 짚는다(원칙 5·6).

docx·pptx·xlsx·pdf도 `inspect_file.py`로 문서 속성, 메모, 변경 추적, 숨김 글자, 본문 숨은 문자를 검사할 수 있다(읽기 전용).

## 프로젝트 지식(컨텍스트) 속 문서를 다룰 때

사용자가 "프로젝트에 있는 ○○", "프로젝트 문서 전부", "컨텍스트의 draft.md"처럼 말하면, 채팅에 첨부한 파일이 아니라 claude.ai 프로젝트 지식이나 작업 폴더에 있는 문서를 뜻한다. 위의 작업 원칙은 그대로 적용하고, 아래를 추가로 지킨다.

**1) 실제 파일부터 찾는다.** 대화창에 보이는 문서 내용은 원본 파일이 아니라 글자만 뽑아 변환한 사본일 수 있다. 그래서 숨은 문자나 메타데이터 검사는 반드시 원본 파일로 해야 한다.
```bash
ls -la /mnt/project /mnt/user-data/uploads 2>/dev/null          # claude.ai: 프로젝트 지식 / 채팅 첨부
find / -name "draft.md" -not -path "/proc/*" 2>/dev/null | head   # 위치를 모를 때
```
Claude Code에서는 현재 작업 폴더(저장소)가 곧 프로젝트다.

**2) 프로젝트 파일은 읽기 전용 원본으로 취급한다.** 프로젝트 지식 폴더 안에는 아무것도 쓰지 않는다(쓰기가 막혀 있는 경우가 많고, 원본 불변 원칙에도 어긋난다). 결과는 출력 폴더에 저장한다.
```bash
python $I /mnt/project/draft.md
python $C /mnt/project/draft.md -o /mnt/user-data/outputs/draft.cleaned.md
python $I /mnt/user-data/outputs/draft.cleaned.md
python $I /mnt/project/draft.md --compare /mnt/user-data/outputs/draft.cleaned.md
```

**3) 파일을 찾지 못하면 단정하지 않는다.** 원본 파일을 찾지 못했다고 말하고, 그 문서를 채팅에 직접 첨부해 달라고 요청한다.
대화창에 보이는 글을 파일로 옮겨 적어서 검사하면 안 된다. 옮겨 적는 과정에서 숨은 문자가 빠지거나 바뀔 수 있고, 메타데이터도 없다. 그래서 "숨은 문자 없음"처럼 잘못된 결론이 나온다.
사용자가 그래도 원하면 "대화창에 보이는 사본을 검사한 것이라 원본 결과와 다를 수 있다"고 밝히고 진행한다.

**4) 여러 문서는 요약표부터 보여준다.**
```bash
python $I /mnt/project/                 # 지원하는 파일 전부 요약표 (이미 정돈된 .cleaned / _clean 파일은 제외)
python $I /mnt/project/ --detail        # 파일별 전체 보고
```
발견 항목이 있는 파일만 골라 하나씩 정돈하고, 파일마다 전후를 비교한다.

**5) 프로젝트에 반영하는 방법을 안내한다.** Claude는 프로젝트 지식을 직접 바꿀 수 없다. 마지막에 이렇게 안내한다.
"정돈된 파일을 내려받아 프로젝트 지식에 올리고, 원본을 바꿀 생각이면 기존 파일은 직접 지워 주세요."

**6) 다른 작업 중에 발견했을 때.** 프로젝트 문서를 요약·분석하다가 워터마크 글자나 숨은 문자가 섞여 방해된다면, 원본을 고치지 말고 정돈된 사본을 출력 폴더에 만들어 그걸로 작업을 이어간다. 무엇을 정돈했는지는 한두 줄로 알려준다.

## 보이는 워터마크 작업 순서

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
- 숨은 문자 검사는 알려진 문자 목록과 규칙으로 찾는다. 목록 밖의 새로운 은닉 방식이나 띄어쓰기·문장 부호 패턴에 숨긴 정보는 못 찾을 수 있다.
- 통계적 텍스트 워터마크는 탐지·제거·제거 확인 모두 불가능하다(원칙 5·6).
- .hwp 변환은 LibreOffice 버전에 따라 안 될 수 있다. 그때는 한글에서 docx나 PDF로 저장해 달라고 안내한다.
