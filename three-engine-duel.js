// 三引擎对拍：网页 index.html / Python 内核 / n8n 节点，同一批线索必须判一样
// 网页版是客户第一眼看到的东西，跟内核不一致 = 客户当场质疑"你自己都对不上"。
const fs = require('fs');
const path = require('path');

const WEB = '/workspace/ai-money-system/线索体检网页';
const html = fs.readFileSync(path.join(WEB, 'index.html'), 'utf8');
const rules = fs.readFileSync(path.join(WEB, 'rules.js'), 'utf8');
const industryRules = fs.readFileSync(path.join(WEB, 'industry-rules.js'), 'utf8');

// 只取 DOM 渲染之前的纯逻辑部分（到 const META 为止），跟 regress.js 一个路子
let inline = html.split('<script>')[1].split('</script>')[0];
inline = inline.slice(0, inline.indexOf('const META'));
if (!inline.includes('function evaluate')) throw new Error('没找到 evaluate 函数');

const vm = require('vm');
const pure = inline + '\nmodule.exports={evaluate};';
const tmpPure = require('os').tmpdir() + '/web_pure_' + process.pid + '.js';
fs.writeFileSync(tmpPure, pure);
const rctx = vm.createContext({ window: {} });
vm.runInContext(rules, rctx);
vm.runInContext(industryRules, rctx);        // 行业词表也挂上去，否则 IR 取空
global.window = { RULES: rctx.window.RULES, INDUSTRY_RULES: rctx.window.INDUSTRY_RULES };
const evaluate = require(tmpPure).evaluate;
if (typeof evaluate !== 'function') throw new Error('evaluate 没跑出来');

function runWeb(d) {
  const r = evaluate({ name: '', email: '', phone: '', message: '', budget: '', vertical: '', ...d });
  return { score: r.score, level: r.intent };
}

// Python / n8n 用交付包里的对拍逻辑
const { execFileSync } = require('child_process');
const ROOT = '/workspace/ai-money-system/自动化demo';
const wf = JSON.parse(fs.readFileSync(path.join(ROOT, 'n8n/lead-scoring.json'), 'utf8'));
const node = wf.nodes.find((n) => (n.name || '').includes('打分'));
function stripComments(src) {
  let out = '', i = 0, q = null;
  while (i < src.length) {
    const c = src[i], n = src[i + 1];
    if (q) { out += c; if (c === '\\') { out += src[i + 1] || ''; i += 2; continue; } if (c === q) q = null; i++; continue; }
    if (c === '/' && n === '/') { while (i < src.length && src[i] !== '\n') i++; continue; }
    if (c === '/' && n === '*') { i += 2; while (i < src.length && !(src[i] === '*' && src[i + 1] === '/')) i++; i += 2; continue; }
    if (c === '"' || c === "'" || c === '`') { q = c; out += c; i++; continue; }
    out += c; i++;
  }
  return out;
}
const fn = new Function('$input', 'return (function(){\n' + stripComments(node.parameters.jsCode) + '\nreturn [{ json: out }];\n})()');
function runN8n(d) {
  const payload = { name: d.name, email: d.email, phone: d.phone, message: d.message, budget_raw: d.budget };
  const items = [{ json: { payload, fingerprint: 'x' } }];
  const out = fn({ first: () => items[0], last: () => items[0], all: () => items, item: items[0], params: {} });
  return { score: out[0].json.ai_score, level: out[0].json.ai_intent };
}

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
  { name: '杨', message: '小程序多少钱，预算1200元' },
  { name: '黄', message: '做个简单的页面，预算500' },
  { name: '李女士', message: '想了解一下你们有没有做过诊所的案例，有什么功能' }, // 中等意向不能掉进 cold
];

const tmp = '/tmp/three_leads.json';
fs.writeFileSync(tmp, JSON.stringify(leads));
const py = JSON.parse(execFileSync('python3', ['-c', `
import json, sys
sys.path.insert(0, ${JSON.stringify(ROOT)})
from score_leads import process
leads = json.load(open(${JSON.stringify(tmp)}))
reps = [{'id': 1, 'name': 'A', 'active_count': 3, 'available': True, 'industries': None}]
res = process(leads, reps)
print(json.dumps([{'score': r['ai_score'], 'intent': r['ai_intent']} for r in res if r.get('ai_intent')], ensure_ascii=False))
`], { encoding: 'utf8' }));

let agree = 0, disagree = 0;
console.log('序号  线索                     网页        Python      n8n         三家一致');
console.log('─'.repeat(84));
leads.forEach((l, i) => {
  const w = runWeb(l);
  const p = py[i];
  const n = runN8n(l);
  const ok = w.level === p.intent && p.intent === n.level;
  ok ? agree++ : disagree++;
  const f = (x) => `${String(x.score).padStart(3)} ${x.intent || x.level}`;
  console.log(`${String(i + 1).padStart(3)}  ${(l.message || '').slice(0, 16).padEnd(16, '　')}  ${f(w).padEnd(10)}  ${f(p).padEnd(10)}  ${f(n).padEnd(10)}  ${ok ? '✓' : '✗'}`);
});
console.log('─'.repeat(84));
console.log(`三家一致 ${agree}/${leads.length}`);
if (disagree) {
  console.log('\n不一致说明：网页版带行业词表，通用模式下的行业分可能与内核不同步；');
  console.log('分级（hot/warm/cold/spam）必须一致 —— 分数差几分可以接受，档位差就是 bug。');
  process.exit(1);
}
