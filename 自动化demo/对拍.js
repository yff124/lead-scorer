#!/usr/bin/env node
/**
 * 双引擎对拍（n8n 交付包自带）
 * ------------------------------------------------------------------
 * 作用：同一批线索，分别用 Python 内核和 n8n 节点代码打分，逐条比对分级。
 *      两边结果必须完全一致 —— 否则"本地试是 hot，上线变 warm"，客户会直接不信。
 *
 * 用法：node 对拍.js
 * 依赖：node（>=16）、python3（不需要装任何 npm 包）
 *
 * 客户改规则时怎么用：
 *   1. 改 score_leads.py 里的词表/分值
 *   2. 改 n8n/lead-scoring.json 里「④ 打分」节点的代码（照抄同一套规则）
 *   3. 跑本脚本。有一条 ✗ 就说明两边不一致，改到全绿再上线。
 */
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
// 不依赖第三方包：自己剥注释，避免客户环境装不上
function stripComments(src) {
  let out = '', i = 0, q = null, tpl = 0;
  while (i < src.length) {
    const c = src[i], n = src[i + 1];
    if (q) {                                   // 字符串里：原样抄
      out += c;
      if (c === '\\') { out += src[i + 1] || ''; i += 2; continue; }
      if (c === q) q = null;
      i++; continue;
    }
    if (c === '/' && n === '/') { while (i < src.length && src[i] !== '\n') i++; continue; }
    if (c === '/' && n === '*') { i += 2; while (i < src.length && !(src[i] === '*' && src[i + 1] === '/')) i++; i += 2; continue; }
    if (c === '"' || c === "'" || c === '`') { q = c; out += c; i++; continue; }
    out += c; i++;
  }
  return out;
}

const ROOT = __dirname;
const WF = path.join(ROOT, 'n8n', 'lead-scoring.json');
const PY = path.join(ROOT, 'score_leads.py');

// ── 从 n8n 工作流里抠出打分节点代码，装进本地运行器 ──────────────
// 坑：节点里是顶层 `return [{json: out}]`，用 new Function 直接包会丢掉返回值，
//     必须再套一层 IIFE，让它"返回给包装函数"。
const wf = JSON.parse(fs.readFileSync(WF, 'utf8'));
const node = wf.nodes.find((n) => (n.name || '').includes('打分'));
if (!node) throw new Error('工作流里找不到「打分」节点');
let code = stripComments(node.parameters.jsCode);
code += '\nreturn [{ json: out }];';          // 节点最后一句是赋值，补一句返回
const fn = new Function('$input', 'return (function(){\n' + code + '\n})()');

function runNode(payload, fingerprint) {
  const items = [{ json: { payload, fingerprint } }];
  const out = fn({ first: () => items[0], last: () => items[0], all: () => items, item: items[0], params: {} });
  if (!Array.isArray(out) || !out[0] || !out[0].json) throw new Error('节点没有返回结果');
  return out[0].json;
}

// ── 用例：覆盖正常、边界、异常三类 ────────────────────────────────
const leads = [
  { name: '张经理', email: 'zhang@factory.com', phone: '13800138000', message: '我们有3个车间想上AI质检，请问报价多少？预算10万', budget: '10万' },
  { name: '李总', message: '我们想上合同审批自动化，预算3万左右，尽快，微信同手机13900139000' },
  { name: '王先生', message: '要做个客户管理系统，电话13800138000，多少钱' },
  { name: '赵', message: '预算800元，想做个AI客服机器人，联系电话13700137000' },
  { name: 'SEO专家', email: 'x@mailinator.com', message: '专业seo服务，点击链接免费领取方案' },
  { name: '小李', email: 'li@gmail.com', message: '你好' },
  { name: '王女士', phone: '13900139000', email: 'wang@clinic.com', message: '想了解一下你们的产品，我们诊所想看看demo' },
  { name: '陈', message: '店铺sku太多了，想上个自动上架，预算多少合适？' },
  { name: '刘律师', message: '律所案件管理太乱，想做个系统，预算大概15k' },
  { name: '某', message: '在吗' },
  { name: '孙', message: '合同怎么签？付款方式？什么时候能开始？预算5万，电话13500135000' },
  { name: '周老师', message: '我们培训机构想招生自动化，预算6万' },
  { name: '吴', message: '免费领取资料' },
  { name: '郑先生', message: '汽修店想做个客户回访系统，报价' },
  { name: '某某', message: '预算15' },
  { name: '杨', message: '小程序多少钱，预算1200元' },   // 预算过低不能进 hot
  { name: '黄', message: '做个简单的页面，预算500' },      // 500 不能被当成 50 万
];

// ── Python 侧：一次性算完，避免每条起一次进程 ────────────────────
const tmp = path.join(require('os').tmpdir(), `duel_${process.pid}.json`);
fs.writeFileSync(tmp, JSON.stringify(leads));
const pyRaw = execFileSync('python3', ['-c', `
import json, sys
sys.path.insert(0, ${JSON.stringify(ROOT)})
from score_leads import process
leads = json.load(open(${JSON.stringify(tmp)}))
reps = [{'id': 1, 'name': 'A', 'active_count': 3, 'available': True, 'industries': None}]
res = process(leads, reps)
print(json.dumps([{'score': r['ai_score'], 'intent': r['ai_intent']} for r in res], ensure_ascii=False))
`], { encoding: 'utf8' });
fs.unlinkSync(tmp);
const py = JSON.parse(pyRaw);

// ── 比对 ─────────────────────────────────────────────────────────
let same = 0, diff = 0;
const rows = [];
console.log('序号  线索（前18字）              Python        n8n           一致');
console.log('─'.repeat(76));
leads.forEach((l, i) => {
  const r = runNode(l, 'fp' + i);
  const p = py[i];
  const ok = p.intent === r.ai_intent;
  ok ? same++ : diff++;
  const ps = `${String(p.score).padStart(3)} ${p.intent}`;
  const ns = `${String(r.ai_score).padStart(3)} ${r.ai_intent}`;
  console.log(`${String(i + 1).padStart(3)}  ${(l.message || '').slice(0, 18).padEnd(18, '　')}  ${ps.padEnd(12)}  ${ns.padEnd(12)}  ${ok ? '✓' : '✗'}`);
  if (!ok) rows.push({ i: i + 1, py: ps, n8n: ns });
});
console.log('─'.repeat(76));
console.log(`分级一致 ${same}/${leads.length}`);
if (diff) {
  console.log('\n不一致明细：');
  rows.forEach((r) => console.log(`  第 ${r.i} 条  Python ${r.py}  vs  n8n ${r.n8n}`));
  console.log('\n两边规则已经跑偏，先对齐再上线。');
  process.exit(1);
}
console.log('两边完全一致，可以放心部署。');
