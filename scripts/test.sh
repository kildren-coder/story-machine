#!/usr/bin/env bash
# 离线测试总入口。AFK 沙箱里的实现 / 评审 agent 和人都只跑这一条:
#   bash scripts/test.sh
# 不烧额度、不碰网络、不碰 vault。两类用例都收:
#   1. scripts/test_*.py —— 自带 main 的断言脚本(退出码非 0 即失败)
#   2. tests/            —— pytest 用例(目录存在才跑)
set -u
cd "$(dirname "$0")/.."
fail=0
for t in scripts/test_*.py; do
  [ -e "$t" ] || continue
  echo "== $t"
  python "$t" || fail=1
done
if [ -d tests ]; then
  echo "== pytest tests/"
  python -m pytest -q tests || fail=1
fi
if [ "$fail" -eq 0 ]; then echo "ALL GREEN"; else echo "FAILED"; fi
exit "$fail"
