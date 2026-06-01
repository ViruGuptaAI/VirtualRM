# CRM Database & Tool Functions

## Overview

The CRM layer consists of:
- **`server/crm.db`** — SQLite database with 15 tables of banking data
- **`server/crm_tools.py`** — 22 Python functions that query the DB and return JSON
- **`server/seed_db.py`** — Schema definition + seed data for 5 demo customers

---

## Database Schema

### Core Tables

#### `customers`
The central customer record.

| Column | Type | Example |
|---|---|---|
| `id` | TEXT (PK) | `rajesh` |
| `name` | TEXT | Rajesh Kumar |
| `email` | TEXT | rajesh.kumar@email.com |
| `phone` | TEXT | +91-98765-43210 |
| `pan` | TEXT | ABCPK1234R |
| `aadhaar_last4` | TEXT | 5678 |
| `date_of_birth` | TEXT | 1985-03-15 |
| `gender` | TEXT | Male |
| `address` | TEXT | ... |
| `city` | TEXT | Mumbai |
| `state` | TEXT | Maharashtra |
| `pincode` | TEXT | 400001 |
| `kyc_status` | TEXT | verified |
| `segment` | TEXT | Premium |
| `relationship_since` | TEXT | 2018-01-15 |
| `cibil_score` | INTEGER | 782 |
| `monthly_income` | INTEGER | 125000 |
| `salary_bank` | INTEGER | 1 (boolean) |
| `emi_delays_12m` | INTEGER | 0 |
| `total_products` | INTEGER | 5 |

#### `accounts`
Savings and salary accounts.

| Column | Type |
|---|---|
| `customer_id` | TEXT (FK) |
| `account_number` | TEXT |
| `account_type` | TEXT (Savings/Salary) |
| `balance` | REAL |
| `interest_rate` | REAL |
| `min_balance` | REAL |
| `ifsc` | TEXT |
| `nomination` | TEXT |
| `opened_on` | TEXT |

#### `credit_cards`

| Column | Type |
|---|---|
| `customer_id` | TEXT (FK) |
| `card_number_last4` | TEXT |
| `card_type` | TEXT (Platinum/Gold/Classic/Elite) |
| `credit_limit` | REAL |
| `available_limit` | REAL |
| `outstanding` | REAL |
| `minimum_due` | REAL |
| `due_date` | TEXT |
| `reward_points` | INTEGER |
| `annual_fee` | REAL |
| `fee_waiver_condition` | TEXT |
| `interest_rate_monthly` | REAL |
| `card_status` | TEXT |
| `issued_on` | TEXT |

#### `loans`

| Column | Type |
|---|---|
| `customer_id` | TEXT (FK) |
| `loan_id` | TEXT |
| `loan_type` | TEXT (Home Loan/Personal Loan/Car Loan/Education Loan) |
| `principal` | REAL |
| `outstanding` | REAL |
| `emi` | REAL |
| `interest_rate` | REAL |
| `tenure_months` | INTEGER |
| `tenure_remaining_months` | INTEGER |
| `start_date` | TEXT |
| `status` | TEXT (active/closed) |

### Product Tables

#### `loan_products`
Bank's loan product catalog. Contains both customer-visible and internal fields.

| Column | Visibility | Purpose |
|---|---|---|
| `product_name` | Public | Home Loan, Personal Loan, etc. |
| `min_amount`, `max_amount` | Public | Loan amount range |
| `base_rate` | Public | Starting rate shown to customers |
| `floor_rate` | **INTERNAL** | Absolute minimum rate (never disclosed) |
| `ceiling_rate` | Public | Maximum rate |
| `max_discount_bps` | **INTERNAL** | Max negotiation room in basis points |
| `min_tenure_months`, `max_tenure_months` | Public | Tenure range |
| `processing_fee_pct` | Public | % of loan amount |
| `foreclosure_fee_pct` | Public | Early closure penalty |
| `ltv_ratio` | Public | Loan-to-value ratio |
| `collateral_required` | Public | Yes/No |
| `eligibility_note` | Public | General eligibility criteria |

**7 loan products:** Home Loan, Personal Loan, Car Loan, Education Loan, Loan Against FD, Gold Loan, Top-up Home Loan.

#### `negotiation_rules`
Per-segment, per-product negotiation parameters.

| Column | Purpose |
|---|---|
| `segment` | Customer segment (Classic/Gold/Premium/Platinum/Elite) |
| `product_name` | Loan product |
| `bonus_discount_bps` | Additional discount for segment (0-40 bps) |
| `fee_waiver_eligible` | Can waive processing fee (1/0) |
| `priority_processing` | Fast-track available (1/0) |
| `retention_offer_bps` | Extra discount for retention (0-25 bps) |

**35 rows:** 5 segments × 7 products.

#### `competitor_rates`
Competitor bank rates for comparison during negotiation.

| Column | Purpose |
|---|---|
| `bank_name` | SBI, HDFC, ICICI, Axis, Kotak |
| `product_name` | Loan product |
| `min_rate`, `max_rate` | Rate range |
| `processing_fee_pct` | Fee % |

**20 rows:** 4-5 banks × 4-5 products.

#### `card_upgrade_paths`

| Column | Purpose |
|---|---|
| `from_card` | Current card tier |
| `to_card` | Upgrade tier |
| `annual_fee` | New card fee |
| `min_spend_required` | Monthly spend threshold |
| `additional_benefits` | Upgrade benefits text |

#### `fd_rate_card`

| Column | Purpose |
|---|---|
| `tenure_label` | e.g., "1 year to 2 years" |
| `min_days`, `max_days` | Tenure range in days |
| `general_rate` | Standard rate |
| `senior_citizen_rate` | +0.5% typically |
| `special_rate` | Promotional rate |
| `special_scheme` | Scheme name if applicable |

**12 rows:** 7-day to 10-year tenures.

### Transaction Tables

#### `transactions`
Combined transaction log across all accounts.

| Column | Type |
|---|---|
| `customer_id` | TEXT (FK) |
| `account_type` | TEXT (savings/credit_card) |
| `date` | TEXT |
| `description` | TEXT |
| `amount` | REAL |
| `type` | TEXT (debit/credit) |
| `category` | TEXT (shopping/dining/travel/bills/salary/transfer) |
| `balance_after` | REAL |

### Deposit Tables

#### `fixed_deposits`

| Column | Type |
|---|---|
| `customer_id` | TEXT (FK) |
| `fd_number` | TEXT |
| `amount` | REAL |
| `interest_rate` | REAL |
| `tenure_months` | INTEGER |
| `start_date`, `maturity_date` | TEXT |
| `is_tax_saver` | INTEGER (0/1) |
| `auto_renew` | INTEGER (0/1) |

#### `recurring_deposits`

| Column | Type |
|---|---|
| `customer_id` | TEXT (FK) |
| `rd_number` | TEXT |
| `monthly_installment` | REAL |
| `interest_rate` | REAL |
| `tenure_months` | INTEGER |
| `start_date`, `maturity_date` | TEXT |
| `total_deposited` | REAL |

### Other Tables

#### `debit_cards`
Debit card details per customer.

#### `investments`
Investment portfolio — mutual funds, equity, PPF, NPS, Gold ETF.

#### `preapproved_offers`
Pre-approved loan and card offers with amount, rate, and validity.

---

## Demo Customers

| ID | Name | Segment | CIBIL | Income | Salary Bank | EMI Delays | Products |
|---|---|---|---|---|---|---|---|
| `rajesh` | Rajesh Kumar | Premium | 782 | ₹1.25L | Yes | 0 | 5 |
| `priya` | Priya Sharma | Gold | 745 | ₹95K | Yes | 0 | 4 |
| `amit` | Amit Patel | Classic | 698 | ₹65K | Yes | 1 | 3 |
| `sneha` | Sneha Reddy | Platinum | 810 | ₹1.10L | No | 0 | 4 |
| `vikram` | Vikram Singh | Elite | 835 | ₹2.50L | Yes | 0 | 8 |

---

## Tool Functions (22)

### Customer Profile

#### `get_customer_profile(customer_id)`
Returns full customer row from `customers` table.

#### `get_customer_summary(customer_id)`
Aggregated view: profile + all accounts + all cards + active loans. Used internally, not exposed as an agent tool.

### Eligibility & Risk

#### `get_eligibility_assessment(customer_id, product_type)`
**Core risk scoring engine.** Calculates a 0-100 risk score using 6 factors:

| Factor | Max Points | Criteria |
|---|---|---|
| CIBIL Score | 30 | 800+ = 30, 750+ = 25, 700+ = 18, 650+ = 10, <650 = 5 |
| Relationship Tenure | 15 | 7+ yrs = 15, 5+ = 12, 3+ = 8, 1+ = 5, <1 = 2 |
| Relationship Value | 20 | Based on total balance across accounts |
| Payment History | 15 | 0 delays = 15, 1 = 10, 2 = 5, 3+ = 0 |
| Salary Banking | 10 | Yes = 10, No = 3 |
| Product Diversity | 10 | 5+ products = 10, 3+ = 7, 2+ = 4, 1 = 2 |

**Eligibility tiers:**

| Tier | Score | Max Rounds | Meaning |
|---|---|---|---|
| `HIGHLY_ELIGIBLE` | 80+ | 3 | Full negotiation (3 rate tiers) |
| `ELIGIBLE` | 60+ | 2 | Moderate negotiation (2 tiers) |
| `CONDITIONALLY_ELIGIBLE` | 40+ | 1 | Limited negotiation (1 tier) |
| `NOT_ELIGIBLE` | <40 or 4+ delays | 0 | Cannot proceed |

### Negotiation Engine

#### `get_negotiation_terms(customer_id, product_name)`
**The core negotiation rate calculator.** Combines product data, customer eligibility, and segment rules.

**Algorithm:**
1. Fetch `loan_products` row → get `base_rate`, `floor_rate`, `max_discount_bps`
2. Fetch `negotiation_rules` for customer's segment + product → get `bonus_discount_bps`
3. Run `get_eligibility_assessment` → get score, tier, max_rounds
4. Calculate spread: `base_rate - floor_rate`
5. Calculate tiered rates:
   - `round1_rate = base_rate - spread × 0.35` (35% of available discount)
   - `round2_rate = base_rate - spread × 0.65 - segment_shift` (65% + segment bonus)
   - `round3_rate = floor_rate` (absolute minimum)
6. Gate by eligibility: only return as many rounds as `max_rounds` allows

**Return format:**
```json
{
  "customer_segment": "Premium",
  "product": "Home Loan",
  "base_rate": 8.9,
  "negotiation_tiers": [
    {"tier": 1, "rate": 8.67, "conditions": "After value selling and 2-3 turns of resistance"},
    {"tier": 2, "rate": 8.41, "conditions": "After customer rejects first offer..."},
    {"tier": 3, "rate": 8.25, "conditions": "ONLY if customer explicitly threatens to leave..."}
  ],
  "non_rate_tools": ["Processing fee waiver", "Priority processing", ...],
  "fee_waiver_eligible": true,
  "_INTERNAL_do_not_disclose": { "floor_rate": 8.25, "max_discount_bps": 75 }
}
```

The `_INTERNAL_do_not_disclose` field is included for the model's internal reference but the agent is instructed to NEVER reveal these values.

### Loan Tools

#### `get_active_loans(customer_id)`
All active loans with EMI, rate, outstanding, tenure remaining.

#### `get_loan_product_details(product_name)`
Customer-facing fields only. **Hides** `floor_rate` and `max_discount_bps`.

#### `get_preapproved_offers(customer_id)`
Pre-approved loan and card offers.

#### `calculate_emi(principal_lakhs, annual_rate, tenure_years)`
Standard reducing balance formula:
```
r = annual_rate / 12 / 100
n = tenure_years × 12
EMI = P × r × (1+r)^n / ((1+r)^n - 1)
```

Returns EMI, total payment, total interest with human-readable formatting (lakhs/crores).

**Note:** Input is `principal_lakhs` (not raw INR) and `tenure_years` (not months).

#### `get_competitor_rates(product_name)`
SBI, HDFC, ICICI, Axis, Kotak rates for comparison. Includes market min/max range.

### Credit Card Tools

#### `get_credit_card_details(customer_id)`
All cards with full details.

#### `get_credit_card_transactions(customer_id)`
Last 10 credit card transactions.

#### `get_reward_points(customer_id)`
Points balance + estimated INR value (1 point = ₹0.25).

#### `get_card_spending_analysis(customer_id)`
Monthly average, annual projected (12× monthly), category breakdown, utilization %, and fee waiver eligibility check via regex on `fee_waiver_condition` field.

**Note:** Annualization assumes transactions cover ~1 month. May be inaccurate with sparse data.

#### `check_card_upgrade_eligibility(customer_id)`
Upgrade paths from `card_upgrade_paths` table. Eligibility based on `credit_limit` vs `min_spend_required`.

### Savings Tools

#### `get_account_details(customer_id)`
All savings/salary accounts.

#### `get_fixed_deposits(customer_id)`
All FDs with amount, rate, tenure, maturity, tax-saver flag, auto-renewal.

#### `get_recurring_deposits(customer_id)`
All RDs with monthly installment, rate, balance, maturity.

#### `get_savings_transactions(customer_id)`
Last 10 savings transactions.

#### `get_fd_rate_card()`
FD interest rates by tenure — no customer_id needed.

### General Banking Tools

#### `get_debit_card_details(customer_id)`
Card network, type, daily limit, international status.

#### `get_investments(customer_id)`
Full portfolio — mutual funds, equity, PPF, NPS, Gold ETF with current value and returns %.

#### `get_all_transactions(customer_id)`
Last 15 transactions across all account types.

### Mock External Tools

#### `check_cibil_score(customer_id)`
Mock CIBIL TransUnion bureau pull. Returns score, band (Excellent/Good/Fair/Poor), key factors, active accounts count, and debt-to-income ratio.

#### `check_rbi_repo_rate()`
Mock RBI monetary policy data. Returns repo rate (6.25%), reverse repo (3.35%), last rate cut (Apr 2026, 25 bps), next MPC meeting date.

---

## Tool Dispatch

The `TOOL_FUNCTIONS` dictionary in `crm_tools.py` maps function names to callable functions:

```python
TOOL_FUNCTIONS = {
    "get_active_loans": get_active_loans,
    "get_negotiation_terms": get_negotiation_terms,
    "calculate_emi": calculate_emi,
    ...
}
```

The server uses `inspect.signature()` to dynamically bind parameters — if a tool function accepts `customer_id`, the server auto-injects it from the session. Other parameters come from the LLM's function call arguments.

---

## Regenerating the Database

```bash
cd server
python seed_db.py
```

This drops all existing tables and recreates them with fresh seed data. The database file is `server/crm.db` and is gitignored.
