# WaterMarkRemover

이미지에서 워터마크·로고·글씨·날짜 도장을 지우는 도구입니다.
지울 곳을 마스크로 잡고 OpenCV inpainting으로 주변 픽셀을 채워 넣습니다.

같은 도구를 세 가지 방식으로 쓸 수 있습니다.

| 어디서 | 어떻게 |
|---|---|
| 터미널 | `python .claude/skills/watermark-remover/scripts/remove_watermark.py ...` |
| Claude Code | 이 저장소를 열면 `watermark-remover` 스킬이 자동으로 잡힘. "이 사진 워터마크 지워줘" 라고 말하거나 `/watermark-remover` 입력 |
| claude.ai 채팅 | `dist/watermark-remover.zip`을 스킬로 업로드 (아래 참고) |

## 설치

```bash
git clone https://github.com/argarg38/WaterMarkRemover.git
cd WaterMarkRemover
pip install -r requirements.txt
```

## 터미널에서 쓰기

```bash
S=.claude/skills/watermark-remover/scripts/remove_watermark.py

# 오른쪽 아래 반투명 흰 글씨 자동 탐지 + 비교 이미지 저장
python $S photo.jpg --auto --region br --preview

# 영역 직접 지정: x,y,너비,높이 (픽셀 또는 %)
python $S photo.jpg --box 75%,88%,24%,10%

# 폴더 일괄 처리: 여러 장에 같은 자리 같은 워터마크가 있으면 자동으로 찾음 (같은 크기 3장 이상)
python $S photos/ -o photos_clean/ --shared --preview
```

결과는 기본적으로 `photo_clean.jpg`처럼 원본 옆에 저장됩니다. `--preview`를 붙이면 `원본 | 마스크(빨강) | 결과`를 나란히 붙인 비교 이미지도 만들어집니다.

| 옵션 | 설명 |
|---|---|
| `--box X,Y,W,H` | 지울 영역. 여러 번 쓸 수 있음 |
| `--auto` | 자동 탐지. `--region tl/tr/bl/br/top/bottom/center/all`, `--color light/dark/any` |
| `--shared` | 폴더 안 공통 워터마크 탐지 |
| `--mask FILE` | 직접 만든 마스크(흰색 = 지울 곳) |
| `--dilate N` | 마스크를 N픽셀 넓힘 (테두리가 남을 때 키우기, 기본 3) |
| `--threshold N` | 자동 탐지 민감도 (낮을수록 많이 잡음) |
| `--preview`, `--save-mask` | 비교 이미지 / 마스크 저장 |

## claude.ai 채팅에 스킬로 추가하기

1. 이 저장소의 [`dist/watermark-remover.zip`](dist/watermark-remover.zip)을 내려받습니다.
2. claude.ai → **설정(Settings) → 기능(Capabilities)** 에서 **코드 실행 및 파일 생성**이 켜져 있는지 확인합니다.
3. 같은 화면의 **스킬(Skills)** 에서 **스킬 업로드**를 눌러 zip 파일을 올리고 켭니다.
4. 새 채팅에 이미지를 올리고 "워터마크 지워줘"라고 하면 Claude가 스킬을 써서 결과 파일을 돌려줍니다.

스킬 내용을 고친 뒤에는 `bash tools/build_skill_zip.sh`로 zip을 다시 만들고 다시 업로드하세요.

## 한계

- 작은 글씨·로고에 잘 맞습니다. 복잡한 그림 위의 큰 워터마크나 사진 전체를 덮는 반복 워터마크는 흔적이 남을 수 있습니다.
- 내가 찍었거나 쓸 권리가 있는 이미지에 쓰세요. 스톡 사진 등 남의 저작물 워터마크를 지워 무단으로 쓰는 것은 저작권 침해가 될 수 있습니다.
