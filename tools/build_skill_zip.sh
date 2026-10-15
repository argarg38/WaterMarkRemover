#!/usr/bin/env bash
# claude.ai 채팅에 올릴 스킬 zip(dist/watermark-remover.zip)을 만든다.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p dist
rm -f dist/watermark-remover.zip
(cd .claude/skills && zip -rq ../../dist/watermark-remover.zip watermark-remover -x '*/__pycache__/*')
echo "dist/watermark-remover.zip 생성 완료"
