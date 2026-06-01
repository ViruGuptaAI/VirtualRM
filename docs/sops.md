# Standard Operating Procedures (SOPs)

## Overview

SOPs are structured workflows that guide each specialist agent through specific customer scenarios. Each SOP defines:

- **Steps** — ordered actions the agent must follow
- **Tools** — which CRM tools the agent can call (tool filtering)
- **Negotiation logic** — multi-turn resistance patterns, concession tiers
- **Guardrails** — what the agent must never say or do

### SOP Registry

The `SOP_REGISTRY` in `server/sops/__init__.py` maps `(agent_key, sub_intent)` tuples to `(sop_text, frozenset_of_tool_names)`.

**27 SOPs** across 4 specialist agents, plus 4 default fallbacks.

When the triage agent routes a call, the server looks up the SOP:
```python
sop_text, tool_names = get_sop(agent_key="loan", sub_intent="rate_reduction")
```

If `tool_names` is a `frozenset`, the server filters the agent's tools to only include those. If `tool_names` is `None` (default SOP), all agent tools are sent.

---

## Loan SOPs (8)

### LOAN_RATE_REDUCTION — The Flagship Negotiation SOP

**File:** `server/sops/loan_sops.py`
**Tools:** `get_active_loans`, `get_preapproved_offers`, `get_negotiation_terms`, `calculate_emi`, `get_competitor_rates`, `get_loan_product_details`, `play_hold_music`

The most complex SOP — implements a realistic multi-turn rate negotiation:

**Step 1 — Fetch Data:**
Call `get_active_loans` + `get_preapproved_offers` simultaneously.

**Step 2 — Anchor & Understand (2-3 turns minimum):**
- Acknowledge the customer's request
- Ask probing questions: "What's prompting this?" / "What rate did they offer?"
- Sell value: zero prepayment penalty, dedicated RM, no hidden charges
- Try non-rate solutions: tenure extension, fee waiver
- MUST call `get_negotiation_terms` before offering any rate

**Step 3 — First Rate Offer:**
- Offer `round1_rate` — make it feel earned
- Call `calculate_emi` to show savings
- STOP. Listen.

**Step 4 — Resist Second Request (2-3 turns):**
- Push back: "This is genuinely a strong rate"
- Offer non-rate sweeteners: processing fee waiver, faster processing
- If customer insists, offer `round2_rate`
- STOP. Listen.

**Step 5 — Final Offer (ONLY if customer explicitly threatens to leave):**
- Customer must say something like "I'll move my loan" or "I'm leaving"
- MUST announce hold: "Let me place your call on hold while I check with my manager"
- MUST call `play_hold_music(duration=5)`
- After hold: "Thank you for holding. I spoke with my manager. We can do {round3_rate}%..."
- This is FINAL.

**Step 6 — Hard Stop:**
If customer demands lower than floor: offer 7-day rate lock, express genuine regret.

**Rules:**
- NEVER skip rounds. NEVER offer two rates in one response.
- NEVER go below round3_rate.
- NEVER use internal terminology: "round", "tier", "concession".
- If customer asks for "best/final/last rate" — do NOT skip. Work through tactics.

---

### LOAN_NEW_INQUIRY

**Tools:** `get_eligibility_assessment`, `get_preapproved_offers`, `check_cibil_score`, `get_loan_product_details`, `calculate_emi`, `get_negotiation_terms`, `get_competitor_rates`, `play_hold_music`

**Step 1:** Understand need — ask loan type and approximate amount.
**Step 2:** Check eligibility + pre-approved offers (call simultaneously).
- If pre-approved offer matches → priority pitch, skip to Step 4
- If NOT eligible → explain gap, suggest next steps, stop
- If eligible → present qualification

**Step 3:** Product details with **amount validation**.
- Compare requested amount vs product's max_amount
- If exceeds limit → flag IMMEDIATELY, suggest alternatives
- NEVER proceed as if full amount is approved

**Step 4:** EMI illustration — show ONE option first. Don't suggest negotiation.

**Step 5:** Rate negotiation (only if customer pushes back) — full 3-phase negotiation with hold music for final offer.

**Step 6:** Proceed to application — initiate with confirmed terms.

---

### LOAN_STATUS

**Tools:** `get_active_loans`, `get_negotiation_terms`, `calculate_emi`, `get_competitor_rates`, `play_hold_music`

**Step 1:** Fetch active loans.
**Step 2:** Present summary with remaining tenure and EMI.
**Step 3:** Proactive advisory — if rate seems high vs current market, offer rate reduction.
**Step 4:** If customer wants rate reduction → full multi-turn negotiation flow.

---

### LOAN_FORECLOSURE

**Tools:** `get_active_loans`, `get_loan_product_details`

**Goal:** Retain the loan.

**Step 1:** Fetch loan details.
**Step 2:** Show foreclosure cost (penalty + charges).
**Step 3:** Negotiate — offer rate reduction, partial prepayment, fee waiver.
**Step 4:** If insists → process with NOC in 15 days.

---

### LOAN_BALANCE_TRANSFER

**Tools:** `get_active_loans`, `get_competitor_rates`, `calculate_emi`

**Step 1:** Gather competitor details.
**Step 2:** Compete on rate.
**Step 3:** Show savings with EMI comparison.
**Step 4:** Address hassle — "We handle everything, 7-10 days."

---

### LOAN_EMI_RESTRUCTURE

**Tools:** `get_active_loans`, `calculate_emi`

Three options presented:
1. **Tenure extension** — show extra interest cost
2. **EMI holiday** — up to 3 months
3. **Step-up EMI** — starts lower, increases over time

---

### LOAN_PREAPPROVED

**Tools:** `get_preapproved_offers`, `get_eligibility_assessment`, `calculate_emi`

Pitch with urgency + exclusivity. Handle hesitation: "Pre-approved rates are 0.5-1% lower than standard."

---

### LOAN_DEFAULT

**Tools:** All loan agent tools

General fallback for unmatched sub-intents.

---

## Credit Card SOPs (6)

### CC_FEE_NEGOTIATION

**Tools:** `get_credit_card_details`, `get_card_spending_analysis`

3-tier concession system:
1. **Spend-based waiver** — if spending meets waiver condition, grant automatically
2. **50% discount** — partial concession if spending is close
3. **Full waiver** — only if customer threatens to cancel

---

### CC_CANCELLATION — Highest Priority Retention SOP

**Tools:** `get_credit_card_details`, `get_card_spending_analysis`, `get_reward_points`

**Step 1:** Empathize genuinely, ask reason.
**Step 2:** Show consequences — CIBIL impact (credit history length), lost reward points (₹ value), credit utilization effect.
**Step 3:** Counter by reason:
- *Fee issue* → offer waiver
- *Not using* → show spending analysis, suggest uses
- *Better card elsewhere* → highlight unique benefits
- *Service issue* → escalate + goodwill

**Step 4:** Last resort bundle — 2-year fee waiver + double rewards for 6 months + ₹2,000 cashback.
**Step 5:** Graceful close — if customer still insists, process request with 45-day cooling-off period.

---

### CC_UPGRADE

**Tools:** `check_card_upgrade_eligibility`, `get_card_spending_analysis`

Check eligibility → present incremental benefits → if not eligible, show gap and what's needed.

---

### CC_DISPUTE

**Tools:** `get_credit_card_details`, `get_credit_card_transactions`

**Immediate security** → identify transaction → set expectations (7-14 day investigation, provisional credit if >₹5,000).

---

### CC_REWARDS

**Tools:** `get_reward_points`, `get_card_spending_analysis`

Fetch points → present ₹ value → best redemption options (travel = 2x value) → spending tips to earn faster.

---

### CC_LIMIT_INCREASE

**Tools:** `get_credit_card_details`, `get_card_spending_analysis`

Assess utilization → offer permanent (5-7 day processing) or temporary increase (instant, 30-day validity).

---

## Savings SOPs (6)

### SAVINGS_FD_NEW

**Tools:** `get_fd_rate_card`, `get_fixed_deposits`

**Step 1:** Understand need — amount, purpose, timeline.
**Step 2:** Fetch rate card.
**Step 3:** Recommend optimal tenure for best rate.
**Step 4:** Tax-saver pitch (5-year lock-in, Section 80C).
**Step 5:** Large amount strategy — split deposits, TDS threshold (₹40K), FD ladder.

---

### SAVINGS_FD_PREMATURE

**Tools:** `get_fixed_deposits`, `get_fd_rate_card`

**Goal:** Keep the deposit intact.

**Step 1:** Show penalty cost (typically 0.5-1% rate reduction).
**Step 2:** Offer alternatives:
- Overdraft against FD (keep earning interest)
- Loan against FD (lower rate than personal loan)
- Partial break (keep rest earning)
**Step 3:** If insists → process premature withdrawal.

---

### SAVINGS_ACCOUNT_CLOSURE

**Tools:** `get_account_details`, `get_fixed_deposits`, `get_recurring_deposits`

Show consequences: linked FDs will be closed, RDs discontinued, transaction history impacted.

Counter by reason:
- *Better interest* → compare rates, show relationship benefits
- *Min balance* → suggest zero-balance salary account
- *Not using* → show last activity, suggest dormant-to-active conversion
- *Service issue* → escalate + goodwill
- *Moved city* → digital banking + doorstep services

---

### SAVINGS_INVESTMENT

**Tools:** All savings tools

Understand goal → risk-return comparison → goal-based recommendation:
- Emergency fund → liquid fund + savings
- Retirement → PPF + equity MF
- Tax saving → ELSS + tax-saver FD

---

### SAVINGS_RD_INQUIRY

**Tools:** `get_recurring_deposits`, `get_fd_rate_card`

New RD: show growth projections over tenure.
Existing RD: suggest increment for goal acceleration.

---

## General Banking SOPs (6)

### GENERAL_COMPLAINT

**Tools:** `get_customer_profile`, `get_all_transactions`

**Maximum empathy, never defensive.**

Resolve by type with goodwill gestures:
- Waive charges
- Credit interest
- Apology call from branch manager
- Premium support upgrade

Set expectations with reference number.

---

### GENERAL_FRAUD — Highest Priority

**Tools:** `get_debit_card_details`, `get_all_transactions`, `get_customer_profile`

**IMMEDIATE PRIORITY:**
1. Assess scope — which card/account, when, how much
2. Block card immediately
3. Gather details — OTP/PIN shared? Suspicious links clicked?
4. Raise dispute — ref: FR-xxx, 48-hour review, provisional credit within 10 days
5. Security guidance — change passwords, enable alerts

---

### GENERAL_DEBIT_CARD

**Tools:** `get_debit_card_details`, `get_customer_profile`

- Block: 3-5 day replacement
- Limit change: immediate
- International activation: set duration + limit, 3.5% forex fee
- Upgrade pitch: Gold/Platinum tiers

---

### GENERAL_KYC

**Tools:** `get_customer_profile`

Check status → if expired:
- Video KYC: 5 minutes, online
- Branch visit: any branch with Aadhaar + PAN
- Doorstep: premium customers only

PAN linking via net banking or SMS.

---

### GENERAL_INVESTMENT

**Tools:** `get_investments`, `get_customer_profile`

Fetch portfolio → overview with returns → recommend by profile:
- Conservative: FD + debt MF
- Moderate: balanced MF + PPF
- Aggressive: equity MF + direct stocks
- Tax-focused: ELSS + NPS

---

## SOP Design Principles

1. **Tool-first:** Always call CRM tools before giving account-specific information
2. **Graduated concession:** Start from least generous, concede only under pressure
3. **Multi-turn resistance:** Each concession requires 2-3 turns of genuine pushback
4. **Value-before-price:** Always sell the product's value before discussing rate reductions
5. **Retention-first:** For closure/cancellation SOPs, always attempt retention before processing
6. **Never fabricate:** Agents must never invent rates, amounts, or terms — always use tool data
7. **Natural language:** No internal jargon ("round 1", "tier 2") — speak like a real banker
