#!/usr/bin/env bash
# 一条命令跑完全部自检 —— 别人 clone 下来之后，用它自己验证我写的"42 项断言"是不是真的
# 用法：bash 自检.sh
set -u
cd "$(dirname "$0")"

pass=0; fail=0
run() {
  local name="$1"; shift
  echo ""
  echo "═══ $name ═══"
  if "$@" > /tmp/_selfcheck.log 2>&1; then
    tail -3 /tmp/_selfcheck.log
    echo "→ 通过"
    pass=$((pass+1))
  else
    echo "→ 失败："
    tail -20 /tmp/_selfcheck.log
    fail=$((fail+1))
  fi
}

run "网页版回归（预算/联系方式/分级）" node regress.js
run "网页版行业词表（6 个行业）"       node regress-industry.js
run "Python 内核自测"                  python3 ../自动化demo/交付包/score_leads.py --selftest
run "n8n 与 Python 对拍"               node ../自动化demo/交付包/对拍.js
run "300 条压力测试"                   python3 ../自动化demo/交付包/压力测试.py
run "三端一致（网页/Python/n8n）"      node 三引擎对拍.js

echo ""
echo "══════════════════════════════"
if [ $fail -eq 0 ]; then
  echo "全部 $pass 套自检通过。"
else
  echo "$pass 套通过，$fail 套失败。"
fi
exit $fail
