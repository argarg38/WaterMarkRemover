# WaterMarkRemover

이미지와 문서(PDF · Word · PowerPoint · Excel)에서 워터마크를 지우는 도구입니다.

| 형식 | 지우는 방식 | 결과 |
|---|---|---|
| **docx · pptx · xlsx** | 문서 속 워터마크 개체(Word 워터마크, WordArt, 배경 그림, 머리글 그림, 지정 문구 도형)만 삭제 | 본문은 그대로, 편집 가능 |
| **PDF** | 워터마크 주석·워터마크 표시 영역·기울어진/반투명 큰 글씨·지정 문구를 삭제 | 글자 선택·검색 유지 |
| **스캔 PDF · 이미지** | 워터마크 부분을 주변 픽셀로 메움 (OpenCV inpainting) | 작은 워터마크에 적합 |
| .doc .ppt .xls .rtf .odt .hwp | LibreOffice로 docx/pptx/xlsx 변환 후 처리 | 변환된 형식으로 저장 |
| **텍스트 (.md .txt 등)** | 숨은 문자·메타데이터 검사 후 새 파일로 정돈 | 원본 그대로, `이름.cleaned.md` |

같은 도구를 세 곳에서 쓸 수 있습니다.

| 어디서 | 어떻게 |
|---|---|
| 터미널 | `python .claude/skills/watermark-remover/scripts/remove_watermark.py 파일` |
| Claude Code | 이 저장소를 열면 `watermark-remover` 스킬이 자동으로 잡힘. "이 문서 워터마크 지워줘" 또는 `/watermark-remover` |
| claude.ai 채팅 | `dist/watermark-remover.zip`을 스킬로 업로드 (아래 참고) |

## 설치

```bash
git clone https://github.com/argarg38/WaterMarkRemover.git
cd WaterMarkRemover
pip install -r requirements.txt
```

## 터미널에서 쓰기

파일 종류는 확장자로 알아서 구분합니다. 결과는 기본적으로 `원본이름_clean.확장자`로 저장되고 원본은 그대로 둡니다.

```bash
S=.claude/skills/watermark-remover/scripts/remove_watermark.py

# 문서: 먼저 무엇이 지워질지 확인 (아무것도 바꾸지 않음)
python $S 보고서.pdf --list
python $S 보고서.docx --list

# 자동으로 찾아 지우기
python $S 보고서.docx
python $S 보고서.pdf --preview          # 원본|결과 비교 이미지도 저장

# 문구를 지정해서 지우기 (여러 번 가능, 대소문자·띄어쓰기 무시)
python $S 보고서.pdf --text "대외비" --text CONFIDENTIAL
python $S 발표.pptx --text DRAFT

# 스캔한 PDF는 이미지 방식으로
python $S 스캔.pdf --raster --auto --region center --preview

# 이미지
python $S photo.jpg --auto --region br --preview
python $S photo.jpg --box 75%,88%,24%,10%
python $S photos/ -o photos_clean/ --shared   # 여러 장의 공통 워터마크
```

### 텍스트 파일: 숨은 문자·메타데이터 검사

```bash
D=.claude/skills/watermark-remover/scripts

python $D/inspect_file.py draft.md                          # 1) 검사만 (파일 안 바뀜)
python $D/clean_text.py draft.md -o draft.cleaned.md        # 2) 새 파일로 정돈 (원본 덮어쓰기는 거부)
python $D/inspect_file.py draft.cleaned.md                  # 3) 같은 도구로 재검사
python $D/inspect_file.py draft.md --compare draft.cleaned.md   # 4) 전후 비교표
```

찾는 것: 제로폭 문자, 방향 제어 문자, 유니코드 태그 문자(숨은 글자 해독), 이모지가 아닌 곳의 변형 선택자, 제어 문자,
특수 공백, 키릴/그리스 글자가 섞인 단어, BOM, 분리 저장된 한글(NFC), 줄바꿈 혼용, front matter·HTML 주석.
docx·pptx·xlsx·pdf는 문서 속성·메모·변경 추적·숨김 글자도 검사합니다.

> **통계적 텍스트 워터마크**(AI가 글을 만들 때 단어 선택 확률에 심는 패턴)는 이 도구로 탐지·제거·제거 확인을 할 수 없습니다.
> 숨은 문자 0건은 숨은 문자가 없다는 뜻일 뿐, 통계적 워터마크가 없다는 뜻이 아닙니다.

### 주요 옵션

| 옵션 | 대상 | 설명 |
|---|---|---|
| `--list` | 문서 | 바꾸지 않고 지울 항목과 후보(반복 글씨, 머리글/바닥글 내용)만 보여줌 |
| `--text 문구` | 문서 | 그 문구로 된 글자·도형·머리글/바닥글 문구 삭제 |
| `--no-heuristic` | PDF | 기울어진/반투명 큰 글씨 자동 삭제 끄기 |
| `--raster` (+ `--pages 1-3`, `--dpi`) | PDF | 스캔본을 이미지 방식으로 처리 |
| `--behind-images` | docx | 머리글에 '텍스트 뒤'로 깔린 그림도 삭제 |
| `--password` | PDF | 암호 걸린 PDF |
| `--preview` | PDF·이미지 | 비교 이미지 저장 |
| `--box X,Y,W,H` | 이미지 | 지울 영역 (픽셀 또는 %) |
| `--auto` (+ `--region`, `--color`) | 이미지 | 반투명 글씨 자동 탐지 |
| `--shared` | 이미지 폴더 | 여러 장 공통 워터마크 탐지 |
| `--dilate`, `--threshold` | 이미지 | 마스크 넓히기 / 탐지 민감도 |

전체 도움말은 `-h`. 형식별 스크립트(`remove_pdf_watermark.py`, `remove_office_watermark.py`)를 직접 실행해도 됩니다.

## claude.ai 채팅에 스킬로 추가하기

1. 이 저장소의 [`dist/watermark-remover.zip`](dist/watermark-remover.zip)을 내려받습니다.
2. claude.ai → **설정(Settings) → 기능(Capabilities)** 에서 **코드 실행 및 파일 생성**이 켜져 있는지 확인합니다.
3. 같은 화면의 **스킬(Skills)** 에서 zip 파일을 업로드하고 켭니다.
4. 채팅에 이미지·PDF·Word 등을 올리고 "워터마크 지워줘"라고 하면 됩니다.
   텍스트 파일은 "draft.md 숨은 문자 검사하고 정돈해줘"처럼 말하면, Claude가 명령어를 먼저 보여주고
   검사 → 새 파일로 정돈 → 재검사·전후 비교 순서로 진행합니다 (원본은 바꾸지 않음).
   문서를 요약·분석시키다가 워터마크 글자가 섞여 방해될 때도 Claude가 이 스킬로 먼저 정리합니다.

스킬 내용을 고친 뒤에는 `bash tools/build_skill_zip.sh`로 zip을 다시 만들고 다시 업로드하세요.

## 한계

- PDF는 만든 프로그램마다 워터마크를 넣는 방식이 달라 자동 탐지가 놓칠 수 있습니다. `--list` → `--text` → `--raster` 순서로 시도하세요.
- PDF `--text`는 본문 문장 안에 같은 단어가 있으면 그 조각도 지울 수 있습니다. 출력 로그를 확인하세요.
- 이미지 방식은 작은 글씨·로고에 잘 맞습니다. 페이지 전체를 덮는 반복 워터마크는 흔적이 남을 수 있습니다.
- 내가 만들었거나 쓸 권리가 있는 파일에 쓰세요. 남의 저작물 워터마크를 지워 무단으로 쓰는 것은 저작권 침해가 될 수 있습니다.
