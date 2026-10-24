#!/usr/bin/env bash
# 一条命令跑完全部自检 —— 不用 clone，不用装东西，只要 node 和 python3。
#
# 用法：  bash 自检.sh
#
# 它会自动把需要的文件下载到一个临时目录，然后跑 6 套测试。
# 这样做的原因：光看网页上写"42 项断言"没意义，得能自己跑出来才算数。
set -u

BASE="https://yff124.github.io/lead-scorer"
WORK="$(mktemp -d)/lead-scorer-check"
mkdir -p "$WORK/自动化demo" "$WORK/自动化demo/n8n"
cd "$WORK"

echo "下载文件到 $WORK ..."
fail_dl=0
for f in index.html rules.js industry-rules.js regress.js regress-industry.js three-engine-duel.js; do
  curl -sfL --max-time 30 -o "$f" "$BASE/$(python3 -c "import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1]))" "$f")" || { echo "  下载失败: $f"; fail_dl=1; }
done
for f in score_leads.py 对拍.js 压力测试.py lead-scoring.json; do
  curl -sfL --max-time 30 -o "自动化demo/$f" "$BASE/%E8%87%AA%E5%8A%A8%E5%8C%96demo/$f" || { echo "  下载失败: $f"; fail_dl=1; }
done
cp 自动化demo/lead-scoring.json 自动化demo/n8n/lead-scoring.json
[ $fail_dl -ne 0 ] && { echo "有文件没下下来，检查网络。"; exit 2; }
echo "下载完成。"
echo ""

pass=0; fail=0
run() {
  local name="$1"; shift
  echo "═══ $name ═══"
  if "$@" > _log.txt 2>&1; then
    grep -E "总计|全部通过|分级一致|三家一致" _log.txt | tail -2
    echo "→ 通过"
    pass=$((pass+1))
  else
    echo "→ 失败："
    tail -15 _log.txt
    fail=$((fail+1))
  fi
  echo ""
}

run "网页版回归（预算/联系方式/分级）" node regress.js
run "网页版行业词表（6 个行业）"       node regress-industry.js
run "Python 内核自测"                  python3 自动化demo/score_leads.py --selftest
run "n8n 与 Python 对拍"               node 自动化demo/对拍.js
run "300 条压力测试"                   python3 自动化demo/压力测试.py
run "三端一致（网页/Python/n8n）"      node three-engine-duel.js

echo "══════════════════════════════"
if [ $fail -eq 0 ]; then
  echo "全部 $pass 套自检通过。"
else
  echo "$pass 套通过，$fail 套失败。"
fi
echo "（文件留在 $WORK，想自己翻可以去看）"
exit $fail
