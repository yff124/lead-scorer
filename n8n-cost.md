# How much does n8n actually cost? (2026, with real numbers)

Most posts answering this just screenshot n8n's pricing page. That's not the question people are asking. The question is *"what will this cost me, in total, once it's running?"*

I self-host n8n and run a production workflow on it. Here's the real bill.

> **TL;DR** — Under ~3,000 executions/month and no LLM calls, self-hosting costs **almost nothing** (a $8/month VPS, or $0 on hardware you already own). The honest answer is that n8n's own licence is never the expensive part. Your time is.

---

## The official prices (October 2026)

| Plan | Price | Executions | Who it's for |
|---|---|---|---|
| **Community** (self-hosted) | **Free** | Unlimited | Anyone who can run Docker |
| Cloud Starter | €20/mo (billed annually) | 2,500 | Don't want to touch a server |
| Cloud Pro | €50/mo (billed annually) | Custom | Solo builders in production |
| Cloud Business | €667/mo | 40,000 | <100 employees, needs SSO |
| Enterprise | Contact sales | Custom | Compliance requirements |

Two things the pricing page doesn't tell you:

1. **Community Edition has no execution limit.** Cloud plans are priced on executions. Self-hosted is priced on hardware. Once you're past a few thousand executions a month, that distinction does all the work.
2. **"Execution" means a full workflow run**, not a step. n8n doesn't charge per node. A 30-node workflow is one execution.

---

## What it actually cost me

I run a lead-scoring pipeline: webhook receives a lead → clean → dedupe → score → assign to a rep → append to a daily digest.

| Item | Cost |
|---|---|
| n8n Community licence | **€0** |
| VPS (2 vCPU / 4 GB) | **~$8/month** |
| Docker | €0 |
| Database | SQLite (bundled) — €0 |
| **LLM API calls** | **€0** |
| **Cost per lead scored** | **€0** |

That last row is the one worth explaining.

---

## The part nobody puts in a pricing comparison

The pipeline scores leads using a **deterministic rule engine**, not an LLM. So the marginal cost of processing a lead is exactly zero — no tokens, no per-call fee, no rate limits.

If I'd used an LLM for the same job:

| Approach | Cost per 1,000 leads | Behaviour |
|---|---|---|
| Rule engine | **€0** | Identical output for identical input |
| LLM (small model, 1 call/lead) | ~€0.20–€1.50 | Varies slightly between runs |
| LLM (large model, 1 call/lead) | ~€2–€15 | Better on messy language, still non-deterministic |

Per-lead cost looks trivial either way. It stops looking trivial when you multiply by volume, and it stops being defensible at all when a client asks *"why did this lead score 62 yesterday and 58 today?"*

**Decision rule I use:**
- If the task needs *judgment on unstructured language* → LLM.
- If the task needs *a consistent, auditable decision* → rules. Use the LLM only to pre-classify into buckets the rules then handle.

Most "AI automation" projects I've seen are the second kind mislabelled as the first.

---

## Self-host vs Cloud: the actual break-even

Cloud Starter: €20/month for 2,500 executions = **€0.008/execution**.

A $8/month VPS handles far more than 2,500 executions if your workflows aren't doing heavy compute. So:

| Your monthly executions | Cheaper option |
|---|---|
| < 500 | **Cloud Starter** — €20 vs ~€8, but zero maintenance |
| 500 – 3,000 | Roughly a wash. Cloud if you value your time, self-host if you don't mind a server. |
| > 3,000 | **Self-hosted**, clearly |

But there's a hidden line item: **maintenance**. A self-hosted instance needs backups, updates, TLS, and someone to notice when it stops. If you're not comfortable with that, the €20 is genuinely good value — I'm not going to pretend otherwise to make self-hosting look clever.

---

## The real cost isn't the licence

My actual time breakdown building one production workflow:

| Task | Time |
|---|---|
| Building the workflow itself | ~2 hours |
| Debugging a field-evaluation bug (return values re-evaluated as expressions) | **~3 hours** |
| Debugging a webhook conflict from an old duplicate workflow | **~2 hours** |
| Fixing a currency parser that read a phone number as a budget | ~1 hour |
| Writing the regression tests | ~1 hour |
| **Total** | **~9 hours** |

At a modest $25/hour, that's **$225 of time** to build a workflow that costs €0/month to run.

The licence was never the problem. **The debugging was.**

---

## Three things that will cost you more than the subscription

**1. Silent failures.** A node starts returning null. Nothing errors. Three weeks later your CRM is full of blanks. Budget for error workflows from day one — an error branch that posts to a channel you actually read.

**2. Duplicate workflows.** In older n8n versions, importing a workflow creates a *new* ID and leaves the old one running. Two workflows listening on the same webhook path: whichever registered first wins. You edit workflow #4, workflow #1 serves the traffic, and nothing you change has any effect. This cost me two hours.

**3. No tests.** Without a handful of fixed input/expected-output cases, every change is a gamble. Mine is a 30-line script that POSTs to the webhook and compares the output. That's enough.

---

## Quick answers

**Is n8n free?**
Community Edition is free and unlimited on executions. You pay for the server.

**Is it cheaper than Zapier?**
For volume, yes — dramatically. Zapier prices per task; n8n self-hosted prices per server. At 10,000+ tasks/month the difference is an order of magnitude. At 200 tasks/month, Zapier's convenience may genuinely be worth it.

**Do I need a credit card to start?**
No. `docker run` and you're going.

**What's the minimum server?**
2 vCPU / 4 GB is comfortable for small workloads. 1 GB works for testing.

**What about the LLM costs?**
Only if you choose to call an LLM. The platform itself never requires one.

---

## The honest summary

| | Cost |
|---|---|
| Licence | €0 |
| Infrastructure | €0–8/month |
| Per-execution marginal cost | €0 |
| **Your time to build it properly** | **The actual expense** |

If someone quotes you a big number for "n8n licensing", they're either selling Cloud Business or they haven't looked. The money in this category isn't in the platform — it's in the nine hours of debugging that the platform's documentation doesn't prepare you for.

---

*I build these workflows and publish the tests. The lead-scoring pipeline referenced above is open: [github.com/yff124/lead-scorer](https://github.com/yff124/lead-scorer) — live demo at [yff124.github.io/lead-scorer](https://yff124.github.io/lead-scorer/).*
