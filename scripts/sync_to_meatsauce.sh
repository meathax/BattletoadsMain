#!/bin/bash
# Publish the committed BT project (git HEAD of D:/Arcade/AI/aCORES/BT) to
# meathax/meatsauce at cores/BT. Usage: sync_to_meatsauce.sh "<commit message>"
set -e
SRC=/d/Arcade/AI/aCORES/BT
DST=/d/Arcade/AI/aCORES/_meatsauce_bt
[ -d "$DST/.git" ] || git clone -q https://github.com/meathax/meatsauce.git "$DST"
MSG="${1:-BT: sync from working repository}"
cd "$DST"
git pull --rebase --quiet origin main
rm -rf cores/BT && mkdir -p cores/BT
(cd "$SRC" && git archive HEAD) | tar -x -C cores/BT
git add -A cores/BT
if git diff --cached --quiet; then echo "nothing to publish"; exit 0; fi
git commit -q -m "$MSG" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
git push origin main
git log --oneline -1
