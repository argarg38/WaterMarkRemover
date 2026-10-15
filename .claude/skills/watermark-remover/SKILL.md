---
name: watermark-remover
description: 이미지에서 워터마크·로고·글자·날짜 도장 같은 오버레이를 지울 때 사용. 사용자가 이미지를 올리고 "워터마크 지워줘", "로고 없애줘", "글씨 지워줘", "remove watermark" 등을 요청하거나, 폴더 안 여러 장에서 같은 워터마크를 한꺼번에 지워야 할 때 쓴다. OpenCV inpainting으로 해당 영역을 주변 픽셀로 채운다.
---

# Watermark Remover

이미지의 워터마크 영역을 마스크로 지정한 뒤 OpenCV inpainting으로 주변 픽셀로 메워 지운다.
도구는 이 스킬 폴더의 `scripts/remove_watermark.py` 하나다.

## 사용 범위

사용자가 직접 찍었거나 만든 이미지, 또는 쓸 권리가 있는 이미지에 쓴다(예: 내 사진의 날짜 도장, 내 디자인 시안의 임시 로고, 스캔본의 얼룩).
스톡 사진 사이트나 다른 사람 저작물의 워터마크를 지워서 라이선스 없이 쓰려는 요청이라면 그 목적으로는 돕지 말고, 원본을 구매하거나 허락을 받는 방법을 안내한다.

## 준비

```bash
pip install opencv-python-headless numpy   # 이미 있으면 건너뜀
```

claude.ai 채팅 환경에서는 올린 파일이 보통 `/mnt/user-data/uploads/`에 있고, 결과는 `/mnt/user-data/outputs/`에 저장해야 사용자가 내려받을 수 있다.
스크립트 경로는 이 SKILL.md가 있는 폴더 기준 `scripts/remove_watermark.py`다.

## 작업 순서

1. **이미지를 직접 본다.** 워터마크가 어디에 있는지(모서리/가운데/반복 타일), 밝은지 어두운지, 크기는 어느 정도인지 파악한다.
   이미지 크기는 `python -c "import cv2;print(cv2.imread('파일').shape)"`로 확인.
2. **마스크 방법을 고른다.**
   - 위치가 분명하다 → `--box`. 퍼센트로 써도 된다. 워터마크보다 살짝 넉넉하게 잡되 너무 크면 뭉개진다.
   - 반투명 흰 글씨/로고가 한쪽에 있다 → `--auto --region br` (tl/tr/bl/br/top/bottom/center/all). 어두운 글씨면 `--color dark`.
   - 같은 워터마크가 같은 자리에 있는 여러 장 → 폴더를 넣고 `--shared` (같은 크기 3장 이상).
   - 사용자가 마스크 이미지를 줬다 → `--mask`.
   - 여러 방법을 함께 써도 된다(합집합).
3. **항상 `--preview`를 붙여 실행**하고, 생성된 비교 이미지(원본 | 빨간 마스크 | 결과)를 직접 열어 확인한다.
4. 결과가 아쉬우면 조정해서 다시 돌린다.
   - 워터마크 테두리가 남음 → `--dilate 5~8`
   - 일부를 못 잡음 → `--threshold` 낮추기(예: 12) 또는 `--box` 추가
   - 엉뚱한 곳까지 지워짐 → `--region` 좁히기, `--threshold` 올리기, 또는 `--box`로 전환
   - 큰 영역이 흐릿하게 번짐 → 영역을 작게 여러 개의 `--box`로 나누거나 `--method ns` 시도
5. 결과 파일과 비교 이미지를 사용자에게 전달한다. 지운 면적 %와 남은 한계(아래)를 짧게 알려준다.

## 명령 예시

```bash
S=scripts/remove_watermark.py   # 이 스킬 폴더 기준 경로

# 오른쪽 아래 반투명 흰 글씨 자동 탐지
python $S photo.jpg --auto --region br --preview

# 영역 직접 지정 (x, y, 너비, 높이 — 픽셀 또는 %)
python $S photo.jpg --box 75%,88%,24%,10% -o photo_clean.jpg --preview

# 두 군데 지우기
python $S photo.jpg --box 10,10,200,60 --box 80%,90%,20%,10%

# 폴더 일괄 처리 (공통 워터마크 자동 탐지)
python $S photos/ -o photos_clean/ --shared --preview
```

주요 옵션: `-o` 출력 경로(기본 `원본_clean`), `--preview [경로]` 비교 이미지, `--save-mask [경로]` 마스크 저장,
`--dilate` 마스크 확장(기본 3), `--radius` inpaint 반경(기본 5), `--method telea|ns`.
전체 도움말은 `python $S -h`.

## 한계

- inpainting은 주변으로 메우는 방식이라 **작은 글씨·로고**에 잘 맞는다. 얼굴·글자처럼 복잡한 내용 위의 큰 워터마크는 흔적이 남을 수 있다.
- 사진 전체를 덮는 반복(타일) 워터마크는 이 방식으로 깨끗하게 지우기 어렵다. 그 경우 사용자에게 한계를 솔직하게 말한다.
- 원본 해상도와 형식(PNG 투명 채널 포함)은 유지된다.
