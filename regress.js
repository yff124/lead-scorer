const fs=require('fs'),vm=require('vm');
const ctx={window:{}};vm.createContext(ctx);
vm.runInContext(fs.readFileSync('./rules.js','utf8'),ctx);
global.window={RULES:ctx.window.RULES};
const h=fs.readFileSync('./index.html','utf8');
let js=h.split('<script>')[1].split('</script>')[0];
js=js.slice(0,js.indexOf('const META'));
fs.writeFileSync(require('os').tmpdir()+'/pure.js',js+'\nmodule.exports={evaluate,extractBudgetFromText,extractContacts};');
const P=require(require('os').tmpdir()+'/pure.js');

let pass=0,fail=0;
function chk(name,cond,detail){
  if(cond){pass++;console.log('  ✓ '+name);}
  else{fail++;console.log('  ✗ '+name+(detail?'  → '+detail:''));}
}

console.log('== 预算提取（不能把手机号/数量当钱）==');
const b=[
 ['预算5万左右',50000],['预算 10 万',100000],['预算15k',15000],
 ['费用控制在3万以内',30000],['能出 8000 元',8000],['预算20w',200000],
 ['投入大概50万',500000],['预算15',15000],
 ['电话13800138000',null],           // 关键：手机号不是预算
 ['想做合同审批，报价多少？电话13800138000',null],
 ['8个车间想上AI质检',null],
 ['我们想做个系统',null],['报价多少？',null],
 ['2024年3月开始',null],
];
for(const [t,exp] of b){
  const g=P.extractBudgetFromText(t);
  chk(`"${t}" → ${g}`, g===exp, `期望 ${exp}`);
}

console.log('== 联系方式 ==');
const c=[
 ['电话13800138000','phone'],['test@abc.com','email'],
 ['微信：zhangsan2024','wechat'],
];
for(const [t,k] of c){
  const r=P.extractContacts(t);
  chk(`"${t}" → ${k}`, !!r[k], JSON.stringify(r));
}
chk('"没有联系方式" → 全空', (()=>{const r=P.extractContacts('没有联系方式');return !r.phone&&!r.email&&!r.wechat;})());

console.log('== 端到端分级 ==');
const e=[
 ['高意向+预算+电话','连锁口腔诊所想上客户管理系统，预算5万左右，这周能演示吗？合同开票怎么走 电话13800138000','hot'],
 ['高意向没电话','想做一套合同审批，报价多少？多久能上线','warm'],
 ['垃圾广告','专业代运营，刷单包上首页，加微信送资料','spam'],
 ['几乎没有信息','你好','cold'],
];
for(const [n,m,exp] of e){
  const r=P.evaluate({message:m});
  chk(`${n} → ${r.score}分 ${r.intent}`, r.intent===exp, `期望 ${exp}；理由: ${r.reasons.join('; ')}`);
}
console.log(`\n总计 ${pass} 通过 / ${fail} 失败`);
process.exit(fail?1:0);
