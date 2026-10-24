// 行业词表测试：每个行业的示例话术必须被判为 hot
// 用法: node regress-industry.js
const fs = require('fs'), vm = require('vm'), os = require('os'), path = require('path');

const ctx = { window: {} };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync('./rules.js', 'utf8'), ctx);
vm.runInContext(fs.readFileSync('./industry-rules.js', 'utf8'), ctx);
global.window = { RULES: ctx.window.RULES, INDUSTRY_RULES: ctx.window.INDUSTRY_RULES };

const h = fs.readFileSync('./index.html', 'utf8');
let js = h.split('<script>')[1].split('</script>')[0];
js = js.slice(0, js.indexOf('const META'));
const tmp = path.join(os.tmpdir(), 'pure_ind.js');
fs.writeFileSync(tmp, js + '\nmodule.exports={evaluate};');
const P = require(tmp);

const IR = ctx.window.INDUSTRY_RULES;
let pass = 0, fail = 0;
const chk = (name, cond, detail) => {
  if (cond) { pass++; console.log('  ✓ ' + name); }
  else { fail++; console.log('  ✗ ' + name + (detail ? '\n      → ' + detail : '')); }
};

console.log('== 每个行业的示例话术应判为 hot ==');
for (const k of Object.keys(IR)) {
  const r = P.evaluate({ message: IR[k].demo, vertical: k });
  chk(`${k}（${IR[k].label}）→ ${r.score}分 ${r.intent}`,
      r.intent === 'hot',
      '理由: ' + r.reasons.join('; '));
}

console.log('\n== 跨行业干扰：行业词不应被别的行业误命中 ==');
// 用牙科话术在"汽修"行业下打分，不应识别为牙科行业
{
  const r = P.evaluate({ message: '孩子牙齿不齐想做隐形矫正，多少钱', vertical: '汽修' });
  chk('牙科话术在汽修词表下不识别为口腔', r.industry !== '口腔 / 牙科',
      '实际识别: ' + r.industry);
}
// 通用词表也要能判出基础意向
{
  const r = P.evaluate({ message: '想做一套系统，报价多少？预算5万，电话13800138000', vertical: null });
  chk('通用词表仍能正常判定', r.intent === 'hot' || r.intent === 'warm',
      r.score + '分 ' + r.intent);
}

console.log('\n== 行业词表命中检查：关键黑话必须被识别 ==');
const mustHit = {
  '口腔诊所': '种植牙', '律所': '起诉', '教培': '试听',
  '汽修': '定损', '装修设计': '量房', 'SaaS软件': '私有化部署'
};
for (const [k, word] of Object.entries(mustHit)) {
  const r = P.evaluate({ message: word + '，能安排吗', vertical: k });
  chk(`"${word}" 在 ${k} 下被识别`, r.reasons.join('').includes(word) || r.score > 0,
      '理由: ' + r.reasons.join('; '));
}

console.log('\n== 垃圾词一票否决在各行业都有效 ==');
for (const k of Object.keys(IR)) {
  const r = P.evaluate({ message: '专业代开发票，加微信领免费资料，点击链接', vertical: k });
  chk(`${k} 下垃圾广告仍判 spam`, r.intent === 'spam', r.score + '分 ' + r.intent);
}

console.log(`\n总计 ${pass} 通过 / ${fail} 失败`);
process.exit(fail ? 1 : 0);
