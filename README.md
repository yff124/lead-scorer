# Lead Scorer — score an inbound lead in 30 seconds

**Live demo (no signup, no install):** https://yff124.github.io/lead-scorer/

Paste a real customer message. Get a score, the reasons behind it, and what to do next.

---

## The problem it solves

Small B2B teams treat every inbound lead the same way: *reply and see what happens.*

The result is predictable:

- 70% of inbound is tyre-kickers and spam; sales spends most of its time on people who will never buy
- The one lead that was ready to pay sits unanswered for two days, then buys elsewhere
- When the owner asks "how good were last month's leads?", nobody can answer

This tool replaces gut feel with a written, inspectable rule set.

## What it outputs

For each lead: **score (0–100)**, **tier** (hot / warm / cold / spam), **the exact reasons**, and **the next action**.

Example:

```
Input:  "We run 8 dental clinics, need a CRM, budget around 50k,
         need a demo this week. What's the contract and invoicing process?
         Phone 13800138000"

Output: 85 / 100 — HOT — call within 5 minutes
        Strong buying signals ×3: quote, contract, invoice
        Explicit budget ≥ ¥5,000 (¥50,000, extracted from message body)
        Target industry: Healthcare
        Contact detected: phone 13800138000
```

## Design decisions (and why)

**No LLM.** This is a deterministic rule engine. Same input always gives the same score. That matters because:

- Cost is zero — no API bills, ever
- You can audit every point (the UI shows the full breakdown)
- It cannot quietly change behaviour after a model update

**Runs entirely in the browser.** No backend, no telemetry, no data leaves the machine. It works offline. That removes the single biggest objection enterprise buyers have about lead data.

**Rules are public.** 18 strong-intent phrases, 12 medium-intent, 13 spam signals, 6 industry dictionaries — all in `rules.js`, all editable. The rules aren't the product. *Tuning them to your industry's actual language* is the product.

## Two bugs I hit, documented

I'm including these because they're the kind of thing that separates a demo from something you'd actually deploy.

**1. Phone numbers parsed as budgets.**
"Budget 50k, phone 13800138000" was initially read as a ¥13.8 *billion* budget. The amount regex swallowed the phone number.
Fix: strip phone numbers, 7+ digit runs, dates and SKU codes before extracting currency.

**2. A hot lead scored as cold.**
"Need a contract approval workflow, what's the price?" matched two strong-intent phrases, but got knocked down to 25/100 because it had no phone number and the message was short.
That's backwards — someone asking for a price won't hand over their phone number on the first message.
Fix: when strong-intent phrases are present, missing contact details cost 5 points instead of 20.

Both are covered by regression tests.

## Tests

```bash
node regress.js
```

22 assertions: budget extraction (including "phone number must not become a budget"), contact detection, end-to-end tiering.

Run it after changing any rule and you'll know immediately whether you broke something.

## Three delivery tiers

| Tier | What you get | Use when |
|---|---|---|
| **Web** (this repo) | Paste one lead, see the breakdown | Evaluating whether this is useful at all |
| **Batch** | CSV in → styled Excel out, colour-coded, summary sheet | You have hundreds of old leads to clean up |
| **Automated** | Hooked to your form/webhook: auto-score, auto-assign to a rep, daily digest | You want this running without anyone touching it |

The web tier is free and always will be.

## Stack

Plain HTML/CSS/JS. No build step, no dependencies, no framework. The Python rule engine (`score_leads.py`) mirrors the same logic if you want it server-side.

## Licence

MIT for the code. The rule dictionaries are examples — replace them with your own industry's vocabulary.
