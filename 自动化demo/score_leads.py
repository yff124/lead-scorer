#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
客户线索自动分级器 —— 核心逻辑
================================
不依赖 n8n / Make / Zapier，纯 Python，可独立跑，也可作为 n8n 的 Code 节点。

为什么先写这个：
  平台会变（n8n 涨价、Zapier 改计费），但这套"清洗 → 去重 → 打分 → 路由 → 记录"的逻辑不变。
  先把它跑对，再挂到任何平台上都是平移。

用法：
  python3 score_leads.py --input leads.json --out result.json
  python3 score_leads.py --selftest        # 跑内置测试用例，验证规则

规则 vs LLM：
  默认走规则（零成本、可解释、可复现）。
  规则覆盖不了的模糊语义，才调 LLM——而且只在"值得花钱"的线索上调。
  这样一条线索的 AI 成本可以压到 0.01 元以下。
"""
import json, re, sys, argparse, hashlib
from datetime import datetime, timedelta

# ══════════════════════════════════════════════════════════
#  1. 规则表 —— 客户想改，改这里，不用动代码
# ══════════════════════════════════════════════════════════
HIGH_INTENT = [           # 强意向信号：出现这些词，说明已经想买了
    "报价", "多少钱", "怎么收费", "合同", "签约", "采购", "下单",
    "什么时候能开始", "能开发票", "开票", "预算", "付款方式",
    "quotation", "pricing", "how much", "contract", "invoice", "purchase order",
]
MEDIUM_INTENT = [         # 中等意向：在了解，还没定
    "了解一下", "咨询", "对比", "怎么样", "有什么功能", "看看",
    "demo", "演示", "试用", "案例", "learn more", "compare",
]
LOW_INTENT = [            # 低意向：只是随便问问
    "你好", "在吗", "hello", "hi", "有人吗",
]
SPAM_SIGNALS = [          # 垃圾：直接扔
    "seo服务", "代开发票", "刷单", "加微信领", "免费领取", "博彩", "贷款",
    "点击链接", "中奖", "兼职日结",
    "unsubscribe", "crypto giveaway", "click here to claim",
]
BLOCKED_DOMAINS = [       # 明显是机器人/一次性邮箱
    "mailinator.com", "guerrillamail.com", "10minutemail.com", "tempmail",
]
# 强信号行业词：命中说明是我们想要的客户
TARGET_INDUSTRIES = {
    "制造": ["工厂", "产能", "车间", "制造", "machining", "factory"],
    "电商": ["店铺", "sku", "上架", "电商", "ecommerce", "shopify"],
    "教育": ["课程", "学员", "招生", "培训", "course", "students"],
    "医疗": ["诊所", "门诊", "患者", "医院", "clinic", "patients"],
    "法律": ["律所", "案件", "诉讼", "律师", "law firm", "litigation"],
    "房产": ["楼盘", "中介", "房源", "房产", "real estate", "listing"],
}


# ══════════════════════════════════════════════════════════
#  2. 清洗
# ══════════════════════════════════════════════════════════
def normalize(lead: dict) -> dict:
    """把各种来源的字段统一成一套。真实业务里 80% 的 bug 出在这一步。"""
    out = {
        "source": (lead.get("source") or "unknown").strip().lower(),
        "contact_name": _clean_text(lead.get("name") or lead.get("contact_name") or ""),
        "contact_email": _clean_email(lead.get("email") or lead.get("contact_email") or ""),
        "contact_phone": _clean_phone(lead.get("phone") or lead.get("contact_phone") or ""),
        "message": _clean_text(lead.get("message") or lead.get("content") or lead.get("body") or ""),
        # 预算字段名各来源不一样：budget / budget_raw / budget_text / 预算 都可能。
        # 只认一个的话，webhook 传 budget_raw、CSV 传 budget_raw，
        # 结果全被判成"没预算"——这个 bug 让 300 条测试里 0 条高意向。
        "budget_yuan": _parse_budget(
            lead.get("budget") if lead.get("budget") not in (None, "")
            else lead.get("budget_raw") if lead.get("budget_raw") not in (None, "")
            else lead.get("budget_text") if lead.get("budget_text") not in (None, "")
            else lead.get("预算")
        ),
        "industry": None,
    }
    # 输入框没填预算，就从留言正文里再抠一次（客户常顺手写在正文里）
    if out["budget_yuan"] is None:
        out["budget_yuan"] = _parse_budget_from_text(out["message"])
    # 原始内容一字不丢，出问题能回溯
    out["raw_payload"] = json.dumps(lead, ensure_ascii=False, sort_keys=True)
    return out


def _clean_text(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", str(s))          # 去 HTML
    s = re.sub(r"\s+", " ", s)                    # 压缩空白
    return s.strip()[:4000]                       # 防超长撑爆数据库


def _clean_email(s: str) -> str:
    s = str(s).strip().lower()
    m = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", s)
    return m.group(0) if m else ""


def _clean_phone(s: str) -> str:
    digits = re.sub(r"\D", "", str(s))
    if len(digits) == 13 and digits.startswith("86"):
        digits = digits[2:]
    return digits if 7 <= len(digits) <= 15 else ""


def _parse_budget(v):
    """预算统一成「元」，不是分。

    '1.5万' → 15000    '15k' → 15000    '¥15,000' → 15000    '15万' → 150000
    解析不出来就返回 None，不要瞎猜——瞎猜出来的预算会直接把线索判成 hot。
    """
    if v is None or v == "":
        return None
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    if isinstance(v, int):
        return v if v > 0 else None
    s = str(v).strip().lower().replace(",", "").replace("¥", "").replace("￥", "")
    mult = 1
    if s.endswith("万") or s.endswith("w"):
        mult, s = 10000, s[:-1]
    elif s.endswith("k") or s.endswith("千"):
        mult, s = 1000, s[:-1]
    m = re.search(r"\d+(?:\.\d+)?", s)
    if not m:
        return None
    return int(round(float(m.group(0)) * mult))


def _parse_budget_from_text(text: str):
    """从留言正文里抠预算。

    真实客户极少填分项框，都是在正文里顺手写一句"预算5万左右""大概15k"。
    和网页版 rules.js 的 extractBudgetFromText 保持一致。

    两个必须避开的坑：
      1. 手机号不能被当成金额（13800138000 → 138 亿）
      2. "8个车间"这种数量不能当预算
    """
    if not text:
        return None
    s = str(text).replace(",", "").replace("¥", "").replace("￥", "")
    s = re.sub(r"1[3-9]\d{9}", " ", s)                       # 手机号
    s = re.sub(r"\b\d{7,}\b", " ", s)                        # 7 位以上连号
    s = re.sub(r"\d{4}[-/年]\d{1,2}[-/月]\d{1,2}", " ", s)   # 日期
    s = re.sub(r"[a-zA-Z]{0,3}\d{8,}[a-zA-Z0-9]*", " ", s)   # sku/单号

    # 有锚点词的优先，避免把"8个车间"当预算
    m = re.search(
        r"(?:预算|报价|费用|价格|价位|出价|准备|投入|能出|大概|最多|不超过|控制在|范围)"
        r"[^0-9]{0,6}(\d+(?:\.\d+)?)\s*(万|w|千|k|元|块)?",
        s, re.I,
    )
    if m:
        num = float(m.group(1))
        unit = (m.group(2) or "").lower()
        if unit in ("万", "w"):
            mult = 10000
        elif unit in ("千", "k"):
            mult = 1000
        elif unit:
            mult = 1
        else:
            # 没单位的歧义处理：
            #   "预算15" → 1.5 万（口语里 15 后面省了"万"，按千算）
            #   "预算500" → 500 元，绝不能算成 50 万
            #     压力测试里"预算500"被判成 500000，一条 500 块的活进了 hot，
            #     客户当场就会说"这系统不准"。只有 1–2 位数才按千算。
            mult = 1000 if num < 100 else 1
        n = int(round(num * mult))
        if n > 0:
            return n

    # 兜底：明确带单位的 "5万" "15k" "3千"
    m = re.search(r"(\d+(?:\.\d+)?)\s*(万|w|千|k)(?![a-z])", s, re.I)
    if m:
        num = float(m.group(1))
        unit = m.group(2).lower()
        return int(round(num * (10000 if unit in ("万", "w") else 1000)))
    return None


# ══════════════════════════════════════════════════════════
#  3. 去重
# ══════════════════════════════════════════════════════════
def fingerprint(lead: dict) -> str:
    """同一个邮箱 + 同样内容 = 重复。缺邮箱就退回用手机，都没有就用内容哈希。"""
    key = lead.get("contact_email") or lead.get("contact_phone") or ""
    body = re.sub(r"\s+", "", lead.get("message", "")).lower()
    return hashlib.md5(f"{key}|{body}".encode()).hexdigest()


# ══════════════════════════════════════════════════════════
#  4. 打分 —— 每条规则都留理由，客户问"为什么这单是热的"能答上来
# ══════════════════════════════════════════════════════════
def score(lead: dict):
    reasons, score_val = [], 0
    text = (lead["message"] + " " + lead.get("contact_name", "")).lower()

    # 4.1 垃圾邮件：一票否决
    for sig in SPAM_SIGNALS:
        if sig in text:
            return 0, "spam", [f"命中垃圾词：{sig}"], False
    if lead["contact_email"].split("@")[-1] in BLOCKED_DOMAINS:
        return 0, "spam", ["一次性邮箱"], False

    # 4.2 意向强度（权重最高）
    hit_high_words = [w for w in HIGH_INTENT if w in text]
    hit_high = bool(hit_high_words)
    if hit_high:
        # 命中 2 个以上强意向词，是"已经在问细节"的人，不是路过问价的。
        # 加这 10 分让核心客户稳定进 hot —— 客户看报告时第一眼找的是这类人。
        # （实测：只给 45 分时，"预算3万 + 问合同/报价"这类最该马上打的线索
        #   会被"行业未命中 -5"压到 65，掉进 warm，客户会觉得系统不准。）
        score_val += 45 + (10 if len(hit_high_words) >= 2 else 0)
        lead["high_hits"] = len(hit_high_words)
        reasons.append(f"强意向词 {len(hit_high_words)} 个：{'、'.join(hit_high_words[:3])}")
    else:
        hit_mid = [w for w in MEDIUM_INTENT if w in text]
        if hit_mid:
            # 中等意向给 30 分：刚好落在 warm 区间（≥35 还差一点，
            # 配上任一其他正向信号——有行业、有联系方式齐全、有预算——就能进 warm）。
            # 给 20 分的话，中等意向单独永远到不了 warm，"中等"这个分级形同虚设。
            score_val += 30
            lead["mid_hits"] = 1
            reasons.append(f"中等意向：{'、'.join(hit_mid[:2])}")

    # 4.3 预算
    # 注意：_parse_budget 返回的是「元」，不是分。这里阈值也用元，别再乘 100。
    b = lead["budget_yuan"]
    if b:
        if b >= 5000:
            score_val += 25
            reasons.append(f"预算明确 ≥5000 元（{b} 元）")
        elif b >= 1000:
            score_val += 10
            reasons.append(f"预算 1000–5000 元（{b} 元）")
        else:
            # 预算低于 1000 元基本不是目标客户。加 5 分会让"预算800做官网"
            # 这类线索混进 warm，白占销售时间——和网页版保持一致，明确扣分。
            # 扣 25（不是 15）：否则"预算800 + 问报价"能靠强意向分冲到 warm，
            # 客户会问"800 块的活你也让我打电话？"
            score_val -= 25
            reasons.append(f"预算过低（{b} 元），大概率不是目标客户")
            lead["low_budget"] = True

    # 4.4 行业匹配
    # 行业是"加分项"不是"门槛"：命中给 15，反之轻扣 5 —— 客户要的行业不对，
    # 成交概率本来就低，但也不能一票否决（新行业客户也是客户）。
    hit_ind = False
    for ind, kws in TARGET_INDUSTRIES.items():
        if any(k in text for k in kws):
            lead["industry"] = ind
            score_val += 15
            reasons.append(f"目标行业：{ind}")
            hit_ind = True
            break
    if not hit_ind:
        # 有强意向（问报价/合同/预算）时只轻扣 2：行业对不上但意图明确，
        # 那是要马上回的人，不该因为"不在 6 个行业里"就掉分。
        score_val += -2 if hit_high else -5
        reasons.append("行业未命中（不在预设 6 个行业里）")

    # 4.5 信息完整度
    # 名/邮箱/电话/留言 四项。但"name+phone+message"三项齐的客户，
    # 成交信息已经够了——原先只认四项齐给 10 分，导致这类真实客户少拿 10 分。
    filled = sum(bool(lead[k]) for k in ("contact_name", "contact_email", "contact_phone", "message"))
    if filled >= 3:
        score_val += 10
        reasons.append(f"联系方式齐全（{filled}/4 项）")
    elif filled <= 1:
        # 强意向线索没留电话是正常的 —— 刚问报价的人不会一上来就交底。
        # 一刀切扣 20 分会把"预算10万 + 制造行业 + 问报价"压到 warm，
        # 那条正是最该马上打的。有强意向词时只轻扣。
        # 中等意向也算"有明确需求"：30 + 15(行业) 被 -20 一扣，卡在 25 掉进 cold，
        # 但"问了案例和功能"的客户显然不是路过的。只对"完全没意向词"重扣。
        if hit_high:
            penalty, why = -5, "还没留联系方式（但意向明确，优先回他）"
        elif hit_mid:
            penalty, why = -8, "没留联系方式（在问了，值得追一句）"
        else:
            penalty, why = -20, "联系方式严重缺失"
        score_val += penalty
        reasons.append(why)

    # 4.6 消息太短 = 大概率随便问。但一句话问报价的信息密度其实很高。
    if len(lead["message"]) < 10 and not hit_high:
        score_val -= 15
        reasons.append("消息过短")

    # 4.7 预算封顶：预算不到 5000 元，绝不可能是高意向。
    #     客户说"小程序多少钱，预算1200"——问得很清楚，但这点钱做不了我们的活。
    #     单靠扣分压不住（45+10 强意向 + 30 中意向就冲上去了），必须硬封顶。
    if b and b < 5000:
        score_val = min(score_val, 65)

    score_val = max(0, min(100, score_val))

    # 4.8 分级 + 是否需人工复核
    #    置信度低（分数落在边界 35–50 之间）的必须人看，宁可漏给人工也别错杀
    if score_val >= 70:
        intent = "hot"
    elif score_val >= 35:
        intent = "warm"
    else:
        intent = "cold"
    # 只复核真正"拿不准"的，不要把整个中间段都丢给人。
    # 原来 35–50 全标复核，实测 300 条里 126 条要人看（42%），
    # 那不叫辅助，那叫把活推回给人。
    #
    # 真正需要人看的是两种：
    #   ① 卡在分级线边上（离 hot/warm/cold 的界限 ≤2 分），判上判下都说得通
    #   ② 分数够高（≥70）但没预算——报价前必须人工确认需求
    # 三条以上强意向词 = 客户已经在问细节了，机器再准也得让人扫一眼
    hot_but_manual = len(hit_high_words) >= 3
    near_line = any(abs(score_val - t) <= 2 for t in (35, 70))
    high_no_budget = score_val >= 70 and not b
    needs_review = bool(near_line or high_no_budget or hot_but_manual)
    return score_val, intent, reasons, needs_review


# ══════════════════════════════════════════════════════════
#  5. 路由 —— 谁接单
# ══════════════════════════════════════════════════════════
def route(lead: dict, reps: list):
    """hot 优先给在线且在手最少的；行业对口的优先。"""
    if not reps:
        return None, "没有可用销售，进人工队列"
    cands = [r for r in reps if r.get("available", True)]
    if lead.get("industry"):
        matched = [r for r in cands if not r.get("industries") or lead["industry"] in r["industries"]]
        if matched:
            cands = matched
    if not cands:
        return None, "无人可接，进人工队列"
    cands.sort(key=lambda r: r.get("active_count", 0))
    return cands[0]["id"], f"分配给 {cands[0]['name']}（在手 {cands[0].get('active_count',0)} 条）"


# ══════════════════════════════════════════════════════════
#  6. 主流程
# ══════════════════════════════════════════════════════════
def process(raw_leads, reps=None, seen_fps=None):
    reps = reps or []
    seen_fps = seen_fps if seen_fps is not None else set()
    results = []
    for raw in raw_leads:
        t0 = datetime.now()
        lead = normalize(raw)
        fp = fingerprint(lead)

        if fp in seen_fps:
            results.append({**lead, "status": "duplicate", "ai_score": None,
                            "events": [{"step": "dedup", "result": "skipped",
                                        "detail": "与之前线索重复"}]})
            continue
        seen_fps.add(fp)

        s, intent, reasons, needs_review = score(lead)
        owner, route_note = route(lead, reps)
        elapsed = int((datetime.now() - t0).total_seconds() * 1000)
        score_val = 0 if intent == "spam" else s

        results.append({
            **lead,
            "status": "junk" if intent == "spam" else "new",
            "ai_score": score_val,
            "ai_intent": intent,
            "ai_reason": "；".join(reasons) or "无匹配规则",
            "needs_review": needs_review,
            "owner_id": owner,
            "events": [
                {"step": "ingest",  "result": "ok", "detail": f"来源 {lead['source']}"},
                {"step": "dedup",   "result": "ok", "detail": "未重复"},
                {"step": "score",   "result": "ok", "detail": f"{score_val} 分 / {intent}"},
                {"step": "route",   "result": "ok" if owner else "manual", "detail": route_note},
            ],
            "duration_ms": max(elapsed, 1),
        })
    return results


# ══════════════════════════════════════════════════════════
#  7. 自测 —— 每次改规则都跑一遍，防止改坏
# ══════════════════════════════════════════════════════════
CASES = [
    # (描述, 输入, 期望 intent)
    ("明确要报价", {"name":"张经理","email":"zhang@factory.com","phone":"13800138000",
                  "message":"我们有3个车间想上AI质检，请问报价多少？预算10万",
                  "budget":"10万","source":"form"}, "hot"),
    ("随便问问", {"name":"小李","email":"li@gmail.com","message":"你好","source":"wechat"}, "cold"),
    ("垃圾邮件", {"name":"SEO专家","email":"x@mailinator.com",
                 "message":"专业seo服务，点击链接免费领取方案","source":"form"}, "spam"),
    ("中等意向", {"name":"王女士","email":"wang@clinic.com","phone":"13900139000",
                 "message":"想了解一下你们的产品，我们诊所想看看demo","source":"form"}, "warm"),
]


def selftest():
    print("=" * 58)
    print(" 规则自测")
    print("=" * 58)
    ok = True
    reps = [{"id": 1, "name": "销售A", "active_count": 3, "available": True, "industries": None}]
    for desc, inp, expect in CASES:
        r = process([inp], reps)[0]
        got = r["ai_intent"]
        hit = got == expect
        ok &= hit
        print(f"{'✓' if hit else '✗'} {desc:<10} 期望 {expect:<5} 实际 {got:<5} "
              f"分 {r['ai_score']:<3} | {r['ai_reason'][:40]}")
    # 去重测试
    print()
    dup = process([CASES[0][1], CASES[0][1]], reps)
    d = dup[1]["status"] == "duplicate"
    ok &= d
    print(f"{'✓' if d else '✗'} 重复线索识别   第二条状态 = {dup[1]['status']}")
    # 预算解析
    for raw, exp in [("1.5万", 15000), ("¥15,000", 15000), ("15k", 15000), ("15万", 150000), ("abc", None)]:
        got = _parse_budget(raw)
        h = got == exp
        ok &= h
        print(f"{'✓' if h else '✗'} 预算解析 {raw!r:<12} → {got}")

    # ── 以下是两个真实踩过的 bug，必须钉死，不能再犯 ──

    # bug 1：字段名不一致。webhook 传 budget_raw，内核只读 budget，
    #        导致 300 条测试里 0 条高意向。现在两种写法都要认。
    print()
    for field in ("budget", "budget_raw", "budget_text", "预算"):
        r = process([{"message": "想上AI质检，报价多少", field: "10万"}], reps)[0]
        h = r["budget_yuan"] == 100000
        ok &= h
        print(f"{'✓' if h else '✗'} 预算字段 {field:<12} → {r['budget_yuan']}")

    # bug 2：正文里写的预算读不到。客户常常写在留言里而不是填框。
    r = process([{"message": "8个车间想上AI质检，报价多少？预算10万"}], reps)[0]
    h = r["budget_yuan"] == 100000 and r["ai_intent"] == "hot"
    ok &= h
    print(f"{'✓' if h else '✗'} 正文预算识别    {r['budget_yuan']} 元 / {r['ai_intent']}")

    # bug 3：手机号被当预算（网页版遇到过，内核也要防）
    r = process([{"message": "想做合同审批，报价多少？电话13800138000"}], reps)[0]
    h = r["budget_yuan"] is None
    ok &= h
    print(f"{'✓' if h else '✗'} 手机号不当预算  budget_yuan = {r['budget_yuan']}")

    # bug 4：预算过低不能混进 warm
    r = process([{"message": "想做个官网，预算800元，能便宜点吗"}], reps)[0]
    h = r["ai_intent"] == "cold"
    ok &= h
    print(f"{'✓' if h else '✗'} 预算过低降级    {r['ai_score']} 分 / {r['ai_intent']}")

    # bug 5：复核比例不能高得离谱（实测超过 40% 就失去意义）
    batch = [{"message": m, "budget": b, "contact_email": f"x{i}@t.com", "name": "客户"}
             for i, (m, b) in enumerate([
                 ("8个车间想上AI质检，报价多少？预算10万", "10万"),
                 ("想做合同审批，报价多少", ""),
                 ("在吗", ""),
                 ("专业代开发票加微信", ""),
                 ("想了解一下你们案例", ""),
                 ("做官网，预算800元", "800"),
                 # 三条以上强意向词 = 客户在问细节，必须人看一眼（这是刻意加的一条规则）
                 ("合同怎么签？付款方式？什么时候能开始？预算5万", "5万"),
                 ("报价、开发票、预算都想知道，我们是工厂", "8万"),
             ] * 10)]
    res = process(batch, reps)
    rev = sum(1 for x in res if x.get("needs_review"))
    rate = rev / len(res) * 100
    h = rate <= 25
    ok &= h
    print(f"{'✓' if h else '✗'} 复核比例       {rate:.0f}%（{rev}/{len(res)}，应 ≤25%）")

    print()
    print("全部通过" if ok else "有失败项，必须修")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input")
    ap.add_argument("--out")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        sys.exit(selftest())
    if not a.input:
        ap.print_help(); sys.exit(1)
    leads = json.load(open(a.input, encoding="utf-8"))
    reps = [{"id": 1, "name": "销售A", "active_count": 2, "available": True, "industries": None},
            {"id": 2, "name": "销售B", "active_count": 0, "available": True, "industries": ["医疗", "法律"]}]
    res = process(leads, reps)
    out = a.out or "result.json"
    json.dump(res, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    # 给人看的摘要
    from collections import Counter
    c = Counter(r["ai_intent"] for r in res if r.get("ai_intent"))
    print(f"处理 {len(res)} 条：{dict(c)}")
    print(f"明细已写入 {out}")


if __name__ == "__main__":
    main()
