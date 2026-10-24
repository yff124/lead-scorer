#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
300 条压力测试 —— 验证规则引擎在"真实脏数据"下的表现
--------------------------------------------------------
不是随便造 300 条，而是按真实表单的分布造：
  45% 正常询价（含各种写法：万/w/k/元、写在正文里、写在框里）
  15% 只问不买（了解一下、在吗、你好）
  15% 垃圾广告（SEO、代开发票、博彩、贷款）
  10% 预算过低（想做官网 500 块那种）
  10% 联系方式残缺
   5% 边界样品（预算刚好卡线、消息刚好 10 字）

用法：python3 压力测试.py
"""

import random
import sys
from collections import Counter

sys.path.insert(0, ".")
from score_leads import process, selftest  # noqa: E402

random.seed(20260724)

REPS = [{"id": 1, "name": "A", "active_count": 3, "available": True, "industries": None}]

# 每条模板用 {u} 占位一个唯一编号，避免 300 条里出现重复内容被判 duplicate
BUY = [
    "我们有{u}个车间想上AI质检，请问报价多少？预算{b}",
    "想做一套合同审批流程（编号{u}），预算{b}，大概多久能上线",
    "店铺sku太多（{u}个）想自动上架，预算{b}，怎么收费",
    "律所案件管理太乱（{u}件在办），想做个系统，预算大概{b}",
    "诊所（{u}张床位）想做个患者回访，预算{b}，能开专票吗",
    "培训机构（{u}个校区）想招生自动化，预算{b}",
    "想做客户管理系统（第{u}期），预算{b}，付款方式怎么走",
    "工厂（{u}条产线）产能报表想自动化，预算{b}，什么时候能开始",
    "电商订单同步想做（日均{u}单），预算{b}，合同怎么签",
    "想采购一套自动化方案（{u}个部门），预算{b}，报价发我",
]

TIRE = [
    "你好",
    "在吗",
    "想了解一下你们的产品",
    "有什么功能",
    "看看案例",
    "你们做过类似的吗",
    "咨询一下",
]

SPAM = [
    "专业seo服务，点击链接免费领取方案",
    "代开发票，加微信领",
    "博彩平台招代理，兼职日结",
    "无抵押贷款，点击链接",
    "刷单兼职日结，加微信",
]

LOW = [
    "想做个官网，预算{b}，能便宜点吗",
    "做个简单的页面，预算{b}",
    "小程序多少钱，预算{b}",
]

BUDGETS = ["5万", "10万", "3万", "8万", "15k", "20k", "6万", "12万", "50000", "80000"]


def build():
    leads = []
    n = 0
    # 45% 正常询价
    for i in range(135):
        tpl = BUY[i % len(BUY)]
        b = BUDGETS[i % len(BUDGETS)]
        msg = tpl.replace("{b}", b).replace("{u}", str(i + 1))
        lead = {"message": msg, "name": f"客户{i}"}
        kind = i % 4
        if kind == 0:                                  # 预算写在框里
            lead["budget"] = b
        elif kind == 1:                                # 只有电话
            lead["phone"] = f"1380013{i:04d}"
        elif kind == 2:                                # 邮箱+电话
            lead["email"] = f"c{i}@corp.com"
            lead["phone"] = f"1390013{i:04d}"
        else:                                          # 全都有
            lead["email"] = f"c{i}@corp.com"
            lead["phone"] = f"1370013{i:04d}"
        leads.append(lead)

    # 15% 只问不买
    for i in range(45):
        leads.append({"message": TIRE[i % len(TIRE)], "name": f"路人{i}",
                      "email": f"p{i}@qq.com"})

    # 15% 垃圾
    for i in range(45):
        leads.append({"message": SPAM[i % len(SPAM)], "name": "推广",
                      "email": f"s{i}@mailinator.com"})

    # 10% 预算过低
    for i in range(30):
        b = ["800元", "500", "1200元", "3000"][i % 4]
        leads.append({"message": LOW[i % len(LOW)].format(b=b), "name": f"小客户{i}",
                      "phone": f"1350013{i:04d}"})

    # 10% 联系方式残缺
    for i in range(30):
        msg = BUY[i % len(BUY)].replace("{b}", "5万").replace("{u}", str(900 + i))
        leads.append({"message": msg})                  # 只有一条消息，啥都没留

    # 5% 边界
    for i in range(15):
        leads.append({"message": ["预算5000", "预算4999", "预算1000",
                                  "我们想上系统", "预算15万左右吧"][i % 5],
                      "name": f"边界{i}", "email": f"b{i}@t.com"})
    return leads


def main():
    print("=" * 62)
    print("  300 条压力测试")
    print("=" * 62)
    leads = build()
    raw = process(leads, REPS)
    dup = sum(1 for r in raw if r.get("status") == "duplicate")
    res = [r for r in raw if r.get("ai_intent")]
    if dup:
        print(f"（其中 {dup} 条被判重复，已剔除）")

    c = Counter(r["ai_intent"] for r in res)
    total = len(res)
    print(f"\n共 {total} 条\n")
    print(f"{'分级':<6}{'数量':>6}{'占比':>8}")
    print("-" * 22)
    for k in ("hot", "warm", "cold", "spam"):
        print(f"{k:<6}{c[k]:>6}{c[k] / total * 100:>7.0f}%")

    rev = sum(1 for r in res if r.get("needs_review"))
    print(f"\n需人工复核 {rev} 条（{rev / total * 100:.0f}%）")

    # 关键正确性检查
    print("\n" + "-" * 62)
    print("关键正确性：")
    checks = []

    # 1. 垃圾必须全判 spam
    spam_ok = all(r["ai_intent"] == "spam" for r in res[180:225])
    checks.append(("45 条垃圾广告全部识别", spam_ok))

    # 2. 正常询价里，带预算的不该进 cold
    normal = res[:135]
    cold_with_budget = sum(1 for r in normal if r["ai_intent"] == "cold" and r.get("budget_yuan"))
    checks.append((f"带预算的正常询价没有掉进 cold（{cold_with_budget} 条）", cold_with_budget == 0))

    # 3. 预算过低不该是 hot
    low = res[225:255]
    low_hot = sum(1 for r in low if r["ai_intent"] == "hot")
    checks.append((f"预算过低没有一条被判 hot（{low_hot} 条）", low_hot == 0))

    # 4. 手机号不能当预算
    phone_as_budget = sum(1 for r in res if (r.get("budget_yuan") or 0) > 5_000_000)
    checks.append((f"没有把手机号解析成预算（{phone_as_budget} 条）", phone_as_budget == 0))

    # 5. 分级单调：hot 的平均分 > warm > cold
    def avg(tier):
        v = [r["ai_score"] for r in res if r["ai_intent"] == tier]
        return sum(v) / len(v) if v else 0
    monotone = avg("hot") > avg("warm") > avg("cold")
    checks.append((f"分数单调 hot({avg('hot'):.0f}) > warm({avg('warm'):.0f}) > cold({avg('cold'):.0f})", monotone))

    ok_all = True
    for desc, ok in checks:
        ok_all &= ok
        print(f"{'✓' if ok else '✗'} {desc}")

    print("\n" + "-" * 62)
    print("样例（每条分级抽 2 条）：")
    for tier in ("hot", "warm", "cold", "spam"):
        picked = [r for r in res if r["ai_intent"] == tier][:2]
        for r in picked:
            print(f"  {tier:<5}{r['ai_score']:>3} 分 | {r['ai_reason'][:56]}")

    print()
    print("全部通过" if ok_all else "有失败项")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
