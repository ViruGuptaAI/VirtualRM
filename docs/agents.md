# Agents

## Overview

VirtualRM uses a **multi-agent architecture** with 1 triage agent and 4 specialist agents. All agents share a single Azure Voice Live WebSocket session — the server reconfigures the session mid-call when routing between agents.

### Agent Registry

The `AGENT_REGISTRY` in `server/agents/__init__.py` maps agent keys to their configuration:

```python
AGENT_REGISTRY = {
    "triage":           { "name": "Anika (Virtual RM)",           ... },
    "credit_card":      { "name": "Meera (Credit Card Specialist)", ... },
    "loan":             { "name": "Priya (Loan Specialist)",      ... },
    "savings_account":  { "name": "Kavya (Savings Specialist)",   ... },
    "general_banking":  { "name": "Riya (General Banking)",       ... },
}
```

Each entry contains:

| Field | Purpose |
|---|---|
| `name` | Display name shown in UI and logs |
| `prompt` | System prompt (personality + rules) |
| `voice` | Azure TTS voice ID |
| `tools` | List of function tool definitions |

All agents currently use `en-IN-Diya:DragonHDLatestNeural` — an Azure Dragon HD Neural voice optimized for Indian English.

---

## Anika — Virtual RM (Triage)

**File:** `server/agents/triage_agent.py`

**Role:** First point of contact. Greets the customer, identifies their intent and emotional state, and routes to the appropriate specialist. Never answers domain questions directly.

**Personality:**
- Warm, professional, efficient
- Keeps responses under 2 sentences
- Detects language (Hindi/English/Hinglish) and responds accordingly

**Intent Detection:** Anika classifies the customer's query into one of 4 intents, each with multiple sub-intents:

| Intent | Sub-Intents |
|---|---|
| `loan` | `rate_reduction`, `new_inquiry`, `loan_status`, `foreclosure`, `balance_transfer`, `emi_restructure`, `preapproved` |
| `credit_card` | `fee_waiver`, `cancellation`, `upgrade`, `dispute`, `rewards`, `limit_increase` |
| `savings_account` | `fd_new`, `fd_premature`, `account_closure`, `investment`, `rd_inquiry` |
| `general_banking` | `complaint`, `fraud`, `debit_card`, `kyc`, `investment` |

**Emotional State Detection:**

| State | Priority | Example |
|---|---|---|
| `frustrated` | High | "Your service is terrible" |
| `urgent` | Critical | "I need this done NOW" |
| `confused` | Normal | "I'm not sure what I need" |
| `exploring` | Sales opportunity | "What loans do you offer?" |
| `retention_risk` | Critical | "I'm thinking of closing my account" |

**Tool:** Single function `route_to_agent(intent, sub_intent, summary)` with enum-constrained parameters.

**Key Rules:**
- The server pre-delivers the greeting ("Hello Rajesh! Welcome to Contoso Bank...") — Anika must NOT greet again
- Never attempts to answer domain questions
- Includes emotional state in the summary for the specialist

---

## Meera — Credit Card Specialist

**File:** `server/agents/credit_card_agent.py`

**Role:** Handles all credit card queries — fee negotiations, cancellation retention, upgrades, disputes, rewards, limit changes.

**Personality:**
- Strategic negotiator — never offers best deal first, concedes gradually
- Empathetic but firm
- 2-3 sentences per response
- Always calls tools before giving account-specific info

**Tools (5):**

| Tool | Purpose | Key Data Returned |
|---|---|---|
| `get_credit_card_details` | Card overview | Limit, outstanding, rewards, due date, fees |
| `get_credit_card_transactions` | Recent activity | Last 10 transactions |
| `get_reward_points` | Points balance | Points + INR value (1pt = ₹0.25) |
| `get_card_spending_analysis` | Spending patterns | Monthly avg, annual projected, categories, utilization %, fee waiver eligibility |
| `check_card_upgrade_eligibility` | Upgrade paths | Current tier → eligible upgrades with benefits comparison |

**Security Rule:** Never shares full card numbers, CVV, or OTP.

---

## Priya — Loan Specialist

**File:** `server/agents/loan_agent.py`

**Role:** The most complex agent. Handles new loans, rate negotiations, foreclosure, EMI restructure, balance transfers, and pre-approved offers.

**Personality:**
- Senior loan specialist with "15 years of experience"
- Data-driven — always pulls CRM data before speaking
- Strategic negotiator who genuinely believes the bank's product is worth the price
- NOT a vending machine that drops prices on demand

**Negotiation Tactics (5 core principles):**

1. **Never rush to offer a discount** — listen, empathize, ask questions first
2. **Resist genuinely** — counter-question, reframe, show reluctance, use silence
3. **Non-rate concessions first** — fee waivers, faster processing, top-up facility
4. **Make every basis point feel earned** — show effort, present each concession as significant
5. **Pace** — each rate change requires 2-3 turns of resistance minimum

**Tools (9):**

| Tool | Purpose |
|---|---|
| `get_active_loans` | All active loans with EMI, rate, outstanding, tenure |
| `get_loan_product_details(product_name)` | Bank rate card (base rate, fees, LTV, eligibility) |
| `get_preapproved_offers` | Pre-approved loan/card offers |
| `get_negotiation_terms(product_name)` | **Core negotiation engine** — returns eligibility-gated tiered rates |
| `get_eligibility_assessment(product_type)` | Risk score (0-100), eligibility tier, scoring factors |
| `calculate_emi(principal_lakhs, annual_rate, tenure_years)` | Standard reducing balance EMI calculator |
| `get_competitor_rates(product_name)` | SBI, HDFC, ICICI, Axis, Kotak comparison |
| `play_hold_music(duration)` | Hold music while "checking with manager" (3-8 seconds) |
| `check_cibil_score` | CIBIL TransUnion bureau pull |
| `check_rbi_repo_rate` | Current RBI monetary policy rates |

**Critical Rules:**
- NEVER disclose floor rate, internal minimum, or `_INTERNAL` fields
- NEVER use words "round", "tier", "concession", "negotiation process"
- NEVER skip to better rate on demand — make them earn every basis point
- MUST call `get_negotiation_terms` before offering ANY reduced rate

---

## Kavya — Savings & Deposits Specialist

**File:** `server/agents/savings_agent.py`

**Role:** Handles savings accounts, fixed deposits, recurring deposits, and investment queries.

**Personality:**
- Trusted financial advisor
- Great at explaining returns in simple terms with concrete numbers
- Proactive about savings optimization
- Example: "₹5L at 7.1% for 2 years = ₹74,100 interest"

**Tools (5):**

| Tool | Purpose |
|---|---|
| `get_account_details` | Account numbers, type, balance, interest rate, min balance |
| `get_fixed_deposits` | FD details — number, amount, rate, tenure, maturity, tax-saver, auto-renewal |
| `get_recurring_deposits` | RD details — number, monthly installment, rate, balance, maturity |
| `get_savings_transactions` | Last 10 savings transactions |
| `get_fd_rate_card` | FD interest rates by tenure (7-day to 10-year) |

**Key Rule:** Uses concrete numbers for impact. Never gives tax advice.

---

## Riya — General Banking Specialist

**File:** `server/agents/general_banking_agent.py`

**Role:** Handles complaints, fraud, debit cards, KYC, and general queries.

**Personality:**
- Versatile problem-solver
- Maximum empathy for complaints — never defensive
- Proactive on cross-sell when appropriate

**Tools (4):**

| Tool | Purpose |
|---|---|
| `get_debit_card_details` | Card network, type, daily limit, international status |
| `get_investments` | Mutual funds, equity, PPF, NPS, Gold ETF with current value/returns |
| `get_all_transactions` | Last 15 transactions across savings + credit card |
| `get_customer_profile` | Full profile — name, email, phone, PAN, KYC, segment, tenure |

**Key Rule:** Customer Care number is 1800-123-1234. Maximum empathy for complaints.

---

## How Agent Config is Assembled

When `build_session_config()` is called in `app.py`:

1. **Base prompt** is loaded from the agent's `prompt` field
2. **SOP workflow** is looked up from `SOP_REGISTRY` based on `(agent_key, sub_intent)`
3. **Context header** is prepended: customer name, summary from triage, specialist identity
4. **Tools are filtered** to only those the SOP needs (from the SOP's `frozenset`)
5. Everything is packed into a `session.update` payload with VAD, TTS, and model config

This means each specialist call uses only the tools relevant to the specific SOP — reducing token usage and preventing the LLM from calling irrelevant tools.

---

## Adding a New Agent

1. **Create agent file:** `server/agents/new_agent.py`
   ```python
   PROMPT = """You are [Name], a [role] at Contoso Bank..."""
   TOOLS = [
       {"type": "function", "name": "tool_name", "description": "...", "parameters": {...}},
   ]
   ```

2. **Register in `server/agents/__init__.py`:**
   ```python
   from agents.new_agent import PROMPT as NEW_PROMPT, TOOLS as NEW_TOOLS
   AGENT_REGISTRY["new_intent"] = {
       "name": "Name (Role)",
       "prompt": NEW_PROMPT,
       "voice": "en-IN-Diya:DragonHDLatestNeural",
       "tools": NEW_TOOLS,
   }
   ```

3. **Add SOPs** in `server/sops/new_sops.py` and register in `server/sops/__init__.py`

4. **Update triage agent** — add the new intent + sub-intents to `triage_agent.py`'s routing table and the `route_to_agent` function's intent enum

5. **Add UI card** in `static/index.html` in the agent pipeline sidebar
