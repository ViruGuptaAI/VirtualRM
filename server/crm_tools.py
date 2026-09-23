"""
CRM Tools — SQLite query functions for Voice Live function calling.
Each function takes a customer_id and returns a JSON-serializable dict.
"""

import sqlite3
import re
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "crm.db"


def _query(sql: str, params: tuple = ()) -> list[dict]:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _query_one(sql: str, params: tuple = ()) -> dict | None:
    rows = _query(sql, params)
    return rows[0] if rows else None


# ─── Triage / Common ──────────────────────────────────────────────────────────

def get_customer_profile(customer_id: str) -> dict:
    """Customer name, segment, city, KYC status, relationship tenure."""
    row = _query_one("SELECT * FROM customers WHERE id = ?", (customer_id,))
    if not row:
        return {"error": "Customer not found"}
    return row


def normalize_phone_number(phone: str) -> str:
    """Normalize a phone number to an E.164-like '+' followed by digits."""
    digits = re.sub(r"\D", "", phone or "")
    return f"+{digits}" if digits else ""


def find_customer_id_by_phone(phone: str) -> str | None:
    normalized = normalize_phone_number(phone)
    if not normalized:
        return None
    for row in _query("SELECT id, phone FROM customers"):
        if normalize_phone_number(row.get("phone", "")) == normalized:
            return str(row["id"])
    return None


def verify_customer_voice_pin(customer_id: str, pin: str) -> bool:
    try:
        row = _query_one(
            "SELECT pin FROM customer_voice_pins WHERE customer_id = ?",
            (customer_id,),
        )
    except sqlite3.OperationalError:
        return False
    return bool(row and row.get("pin") == pin)


def get_customer_summary(customer_id: str) -> dict:
    """Quick overview: accounts, cards, loans, FDs — for triage greeting."""
    profile = _query_one(
        "SELECT name, segment, city, relationship_since FROM customers WHERE id = ?",
        (customer_id,),
    )
    if not profile:
        return {"error": "Customer not found"}

    accounts = _query(
        "SELECT account_type, balance FROM accounts WHERE customer_id = ?",
        (customer_id,),
    )
    cards = _query(
        "SELECT card_type, outstanding, reward_points FROM credit_cards WHERE customer_id = ?",
        (customer_id,),
    )
    loans = _query(
        "SELECT loan_type, outstanding, emi FROM loans WHERE customer_id = ? AND status = 'Active'",
        (customer_id,),
    )

    return {
        **profile,
        "accounts": accounts,
        "credit_cards": cards,
        "active_loans": loans,
    }


# ─── Risk & Eligibility Model ────────────────────────────────────────────────

def get_eligibility_assessment(customer_id: str, product_type: str) -> dict:
    """
    Risk-based eligibility assessment. Evaluates customer across 6 dimensions,
    computes a risk score (0-100), and returns eligibility tier + reasons.
    
    product_type: "rate_reduction", "new_loan", "card_upgrade", "limit_increase"
    """
    customer = _query_one("SELECT * FROM customers WHERE id = ?", (customer_id,))
    if not customer:
        return {"error": "Customer not found"}

    accounts = _query(
        "SELECT balance FROM accounts WHERE customer_id = ?", (customer_id,)
    )
    total_deposits = sum(a["balance"] for a in accounts)

    fds = _query(
        "SELECT amount FROM fixed_deposits WHERE customer_id = ?", (customer_id,)
    )
    total_fd = sum(f["amount"] for f in fds)

    investments = _query(
        "SELECT current_value FROM investments WHERE customer_id = ?", (customer_id,)
    )
    total_investments = sum(i["current_value"] for i in investments)

    loans = _query(
        "SELECT outstanding, emi FROM loans WHERE customer_id = ? AND status = 'Active'",
        (customer_id,),
    )
    total_outstanding = sum(l["outstanding"] for l in loans)
    total_emi = sum(l["emi"] for l in loans)

    # ── Calculate relationship tenure in years ──
    from datetime import date
    try:
        since = date.fromisoformat(customer["relationship_since"])
        tenure_years = (date.today() - since).days / 365.25
    except (ValueError, TypeError):
        tenure_years = 0

    monthly_income = customer.get("monthly_income", 0) or 0
    cibil = customer.get("cibil_score", 0) or 0
    salary_bank = customer.get("salary_bank", 0)
    emi_delays = customer.get("emi_delays_12m", 0)
    total_products = customer.get("total_products", 1)
    total_relationship_value = total_deposits + total_fd + total_investments

    # ── SCORING MODEL (0-100) ────────────────────────────────────────
    score = 0.0
    factors = []

    # Factor 1: CIBIL Score (30 points max)
    if cibil >= 800:
        score += 30; factors.append(f"Excellent CIBIL score ({cibil}): +30pts")
    elif cibil >= 750:
        score += 25; factors.append(f"Very good CIBIL score ({cibil}): +25pts")
    elif cibil >= 700:
        score += 15; factors.append(f"Good CIBIL score ({cibil}): +15pts")
    elif cibil >= 650:
        score += 5; factors.append(f"Fair CIBIL score ({cibil}): +5pts")
    else:
        factors.append(f"Low CIBIL score ({cibil}): +0pts — needs improvement")

    # Factor 2: Relationship Tenure (15 points max)
    if tenure_years >= 7:
        score += 15; factors.append(f"Long-standing customer ({tenure_years:.0f} years): +15pts")
    elif tenure_years >= 5:
        score += 12; factors.append(f"Established customer ({tenure_years:.0f} years): +12pts")
    elif tenure_years >= 3:
        score += 8; factors.append(f"Growing relationship ({tenure_years:.0f} years): +8pts")
    elif tenure_years >= 1:
        score += 3; factors.append(f"Relatively new customer ({tenure_years:.1f} years): +3pts")
    else:
        factors.append(f"New customer ({tenure_years:.1f} years): +0pts — build history first")

    # Factor 3: Total Relationship Value (20 points max)
    if total_relationship_value >= 2500000:
        score += 20; factors.append(f"High-value portfolio (₹{total_relationship_value:,.0f}): +20pts")
    elif total_relationship_value >= 1000000:
        score += 15; factors.append(f"Strong portfolio (₹{total_relationship_value:,.0f}): +15pts")
    elif total_relationship_value >= 500000:
        score += 10; factors.append(f"Moderate portfolio (₹{total_relationship_value:,.0f}): +10pts")
    elif total_relationship_value >= 100000:
        score += 5; factors.append(f"Building portfolio (₹{total_relationship_value:,.0f}): +5pts")
    else:
        factors.append(f"Low portfolio value (₹{total_relationship_value:,.0f}): +0pts")

    # Factor 4: Payment History (15 points max)
    if emi_delays == 0:
        score += 15; factors.append("Perfect payment history (0 delays): +15pts")
    elif emi_delays == 1:
        score += 8; factors.append(f"Minor payment delay ({emi_delays} in 12m): +8pts")
    elif emi_delays <= 3:
        score += 3; factors.append(f"Payment delays ({emi_delays} in 12m): +3pts — needs attention")
    else:
        factors.append(f"Frequent delays ({emi_delays} in 12m): +0pts — not eligible")

    # Factor 5: Salary Banking (10 points max)
    if salary_bank:
        score += 10; factors.append("Salary credited to Contoso Bank: +10pts")
    else:
        factors.append("Salary at another bank: +0pts — consider moving salary for better offers")

    # Factor 6: Product Diversity (10 points max)
    if total_products >= 5:
        score += 10; factors.append(f"Deep product engagement ({total_products} products): +10pts")
    elif total_products >= 3:
        score += 7; factors.append(f"Good product engagement ({total_products} products): +7pts")
    elif total_products >= 2:
        score += 3; factors.append(f"Limited products ({total_products}): +3pts")
    else:
        factors.append(f"Single product ({total_products}): +0pts")

    # ── DTI check for new loan eligibility ──
    dti_ratio = round((total_emi / monthly_income * 100), 1) if monthly_income > 0 else 999
    if product_type == "new_loan":
        if dti_ratio > 50:
            factors.append(f"⚠️ High debt-to-income ratio ({dti_ratio}%): EMI burden too high")
        elif dti_ratio > 40:
            factors.append(f"Moderate debt-to-income ratio ({dti_ratio}%): limited additional EMI capacity")

    # ── ELIGIBILITY TIER ─────────────────────────────────────────────
    score = round(score)
    if emi_delays >= 4:
        tier = "NOT_ELIGIBLE"
        max_concession_round = 0
        recommendation = "Customer has frequent payment delays. Not eligible for rate concessions at this time."
    elif score >= 80:
        tier = "HIGHLY_ELIGIBLE"
        max_concession_round = 3
        recommendation = "Excellent profile. Full negotiation range available including retention offer."
    elif score >= 60:
        tier = "ELIGIBLE"
        max_concession_round = 2
        recommendation = "Good profile. Standard and loyalty discounts available. Retention offer only if truly at risk."
    elif score >= 40:
        tier = "CONDITIONALLY_ELIGIBLE"
        max_concession_round = 1
        recommendation = "Average profile. Only standard product discount available. Suggest improving CIBIL or relationship value."
    else:
        tier = "NOT_ELIGIBLE"
        max_concession_round = 0
        recommendation = "Profile does not meet criteria for rate concession. Suggest building credit history."

    return {
        "customer_name": customer["name"],
        "risk_score": score,
        "eligibility_tier": tier,
        "max_concession_round": max_concession_round,
        "recommendation": recommendation,
        "scoring_factors": factors,
        "summary": {
            "cibil_score": cibil,
            "relationship_years": round(tenure_years, 1),
            "total_relationship_value": total_relationship_value,
            "monthly_income": monthly_income,
            "total_emi": total_emi,
            "dti_ratio_pct": dti_ratio,
            "salary_with_us": bool(salary_bank),
            "emi_delays_12m": emi_delays,
            "product_count": total_products,
        },
    }


# ─── Credit Card Agent Tools ─────────────────────────────────────────────────

def get_credit_card_details(customer_id: str) -> dict:
    """Full credit card info: limit, outstanding, rewards, due date, fees."""
    cards = _query(
        "SELECT * FROM credit_cards WHERE customer_id = ?", (customer_id,)
    )
    return {"cards": cards} if cards else {"error": "No credit cards found"}


def get_credit_card_transactions(customer_id: str) -> dict:
    """Recent credit card transactions (last 10)."""
    txns = _query(
        "SELECT date, description, amount, category FROM transactions "
        "WHERE customer_id = ? AND account_type = 'credit_card' "
        "ORDER BY date DESC LIMIT 10",
        (customer_id,),
    )
    return {"transactions": txns}


def get_reward_points(customer_id: str) -> dict:
    """Reward points balance and estimated value."""
    cards = _query(
        "SELECT card_type, reward_points FROM credit_cards WHERE customer_id = ?",
        (customer_id,),
    )
    for c in cards:
        c["estimated_value_inr"] = round(c["reward_points"] * 0.25, 2)
    return {"cards": cards}


def get_card_spending_analysis(customer_id: str) -> dict:
    """Analyze spending patterns from transactions for negotiation and advisory."""
    txns = _query(
        "SELECT amount, category FROM transactions "
        "WHERE customer_id = ? AND account_type = 'credit_card'",
        (customer_id,),
    )
    card = _query_one(
        "SELECT credit_limit, outstanding, annual_fee, fee_waiver_condition, issued_on "
        "FROM credit_cards WHERE customer_id = ? LIMIT 1",
        (customer_id,),
    )
    if not card:
        return {"error": "No credit card found"}

    total_spend = sum(t["amount"] for t in txns)
    category_spend: dict[str, float] = {}
    for t in txns:
        cat = t["category"] or "other"
        category_spend[cat] = category_spend.get(cat, 0) + t["amount"]

    # Annualize (assume transactions cover ~1 month of data)
    monthly_avg = total_spend
    annual_projected = monthly_avg * 12
    utilization = round((card["outstanding"] / card["credit_limit"]) * 100, 1) if card["credit_limit"] else 0

    # Fee waiver check
    waiver_threshold = None
    fee_waiver_condition = card.get("fee_waiver_condition", "")
    if fee_waiver_condition:
        import re
        # Match patterns like "₹3L", "₹3,00,000", "₹300000", "₹2L"
        m = re.search(r'₹([\d,]+)L', fee_waiver_condition)
        if m:
            waiver_threshold = int(m.group(1).replace(",", "")) * 100000
        else:
            m = re.search(r'₹([\d,]+)', fee_waiver_condition)
            if m:
                waiver_threshold = int(m.group(1).replace(",", ""))

    fee_waiver_eligible = bool(waiver_threshold and annual_projected >= waiver_threshold)

    return {
        "total_recent_spend": total_spend,
        "monthly_average_spend": monthly_avg,
        "annual_projected_spend": annual_projected,
        "category_breakdown": category_spend,
        "credit_utilization_pct": utilization,
        "annual_fee": card["annual_fee"],
        "fee_waiver_condition": fee_waiver_condition,
        "fee_waiver_threshold": waiver_threshold,
        "fee_waiver_eligible": fee_waiver_eligible,
        "card_age_since": card["issued_on"],
        "top_category": max(category_spend, key=category_spend.get) if category_spend else None,
    }


def check_card_upgrade_eligibility(customer_id: str) -> dict:
    """Check eligible upgrade paths with benefits comparison."""
    card = _query_one(
        "SELECT card_type, credit_limit, reward_points FROM credit_cards WHERE customer_id = ? LIMIT 1",
        (customer_id,),
    )
    if not card:
        return {"error": "No credit card found"}

    profile = _query_one(
        "SELECT segment FROM customers WHERE id = ?", (customer_id,)
    )
    segment = profile["segment"] if profile else "Classic"

    upgrade_paths = _query(
        "SELECT * FROM card_upgrade_paths WHERE from_card = ?",
        (card["card_type"],),
    )

    eligible = []
    for path in upgrade_paths:
        is_eligible = card["credit_limit"] >= path["min_spend_required"]
        eligible.append({
            "from_card": path["from_card"],
            "to_card": path["to_card"],
            "annual_fee_difference": path["to_annual_fee"] - path["from_annual_fee"],
            "from_annual_fee": path["from_annual_fee"],
            "to_annual_fee": path["to_annual_fee"],
            "new_benefits": path["additional_benefits"],
            "min_spend_required": path["min_spend_required"],
            "eligible": is_eligible,
            "customer_segment": segment,
        })

    return {
        "current_card": card["card_type"],
        "current_limit": card["credit_limit"],
        "upgrade_options": eligible,
    }


# ─── Loan Agent Tools ─────────────────────────────────────────────────────────

def get_active_loans(customer_id: str) -> dict:
    """All active loans with EMI, rate, outstanding, tenure remaining."""
    loans = _query(
        "SELECT * FROM loans WHERE customer_id = ? AND status = 'Active'",
        (customer_id,),
    )
    return {"loans": loans}


def get_loan_product_details(product_name: str) -> dict:
    """Bank rate card for customer-facing info: base rate, tenure, fees, eligibility."""
    row = _query_one(
        "SELECT * FROM loan_products WHERE product_name = ?", (product_name,)
    )
    if not row:
        return {"error": f"Product '{product_name}' not found"}
    # Return only customer-facing fields — hide internal pricing thresholds
    return {
        "product_name": row["product_name"],
        "base_rate": row["base_rate"],
        "ceiling_rate": row["ceiling_rate"],
        "min_amount": row["min_amount"],
        "max_amount": row["max_amount"],
        "min_tenure_months": row["min_tenure_months"],
        "max_tenure_months": row["max_tenure_months"],
        "processing_fee_pct": row["processing_fee_pct"],
        "prepayment_penalty_pct": row["prepayment_penalty_pct"],
        "foreclosure_fee_pct": row["foreclosure_fee_pct"],
        "ltv_ratio": row["ltv_ratio"],
        "collateral_required": row["collateral_required"],
        "eligibility_note": row["eligibility_note"],
    }


def get_preapproved_offers(customer_id: str) -> dict:
    """Pre-approved loan/card offers for this customer."""
    offers = _query(
        "SELECT * FROM preapproved_offers WHERE customer_id = ?",
        (customer_id,),
    )
    return {"offers": offers}


def get_negotiation_terms(customer_id: str, product_name: str) -> dict:
    """Calculate best possible rate for this customer + product, gated by eligibility."""
    profile = _query_one(
        "SELECT segment FROM customers WHERE id = ?", (customer_id,)
    )
    if not profile:
        return {"error": "Customer not found"}

    product = _query_one(
        "SELECT * FROM loan_products WHERE product_name = ?", (product_name,)
    )
    if not product:
        return {"error": f"Product '{product_name}' not found"}

    rules = _query_one(
        "SELECT * FROM negotiation_rules WHERE segment = ? AND product_name = ?",
        (profile["segment"], product_name),
    )

    # ── Run eligibility assessment ────────────────────────────────────
    eligibility = get_eligibility_assessment(customer_id, "rate_reduction")
    risk_score = eligibility["risk_score"]
    max_round = eligibility["max_concession_round"]

    base_rate = product["base_rate"]
    floor_rate = product["floor_rate"]
    max_discount = product["max_discount_bps"]
    bonus_discount = rules["bonus_discount_bps"] if rules else 0
    retention_bps = rules["retention_offer_bps"] if rules else 0

    # ── Proportional tier calculation ─────────────────────────────────
    spread = base_rate - floor_rate
    if spread >= 0.05:
        seg_shift = min(bonus_discount / 100, spread * 0.10)
        round1_rate = round(base_rate - spread * 0.35, 2)
        round2_rate = round(base_rate - spread * 0.65 - seg_shift, 2)
        round3_rate = round(floor_rate, 2)
        round2_rate = max(round2_rate, round3_rate)
        round1_rate = max(round1_rate, round2_rate + 0.05)
    else:
        round1_rate = round2_rate = round3_rate = round(base_rate, 2)

    # ── Gate tiers by eligibility ─────────────────────────────────────
    # If customer isn't eligible for Round 2/3, cap those at Round 1 rate
    tiers = {}
    if max_round >= 1:
        tiers["round1_rate"] = round(round1_rate, 2)
        tiers["round1_label"] = "standard product discount"
        tiers["round1_reason"] = f"Based on your CIBIL score and payment history"
    if max_round >= 2:
        tiers["round2_rate"] = round(round2_rate, 2)
        tiers["round2_label"] = "loyalty + relationship bonus"
        tiers["round2_reason"] = f"Based on your {eligibility['summary']['relationship_years']:.0f}-year relationship and ₹{eligibility['summary']['total_relationship_value']:,.0f} portfolio"
    if max_round >= 3:
        tiers["round3_rate"] = round(round3_rate, 2)
        tiers["round3_label"] = "retention offer (only if threatening to leave)"
        tiers["round3_reason"] = "Special retention pricing for valued customers"

    return {
        "customer_segment": profile["segment"],
        "product": product_name,
        "base_rate": base_rate,
        "ceiling_rate": product["ceiling_rate"],
        "eligibility": {
            "risk_score": risk_score,
            "tier": eligibility["eligibility_tier"],
            "max_round": max_round,
            "top_factors": eligibility["scoring_factors"][:3],
        },
        "negotiation_tiers": tiers,
        "_INTERNAL_do_not_disclose_to_customer": {
            "absolute_floor": floor_rate,
            "max_product_discount_bps": max_discount,
            "segment_bonus_bps": bonus_discount,
            "retention_bps": retention_bps,
        },
        "fee_waiver_eligible": bool(rules["fee_waiver_eligible"]) if rules else False,
        "priority_processing": bool(rules["priority_processing"]) if rules else False,
        "processing_fee_pct": product["processing_fee_pct"],
        "prepayment_penalty_pct": product["prepayment_penalty_pct"],
        "foreclosure_fee_pct": product["foreclosure_fee_pct"],
    }


def calculate_emi(principal_lakhs: float, annual_rate: float, tenure_years: int) -> dict:
    """Calculate EMI using standard reducing balance formula.
    principal_lakhs: loan amount in LAKHS (e.g. 10 for ₹10 lakh, 500 for ₹5 crore)
    tenure_years: loan tenure in YEARS (e.g. 10, 20, 30)
    """
    principal = principal_lakhs * 1_00_000  # Convert lakhs to INR
    tenure_months = tenure_years * 12
    monthly_rate = annual_rate / 12 / 100
    if monthly_rate == 0:
        emi = principal / tenure_months
    else:
        emi = principal * monthly_rate * (1 + monthly_rate) ** tenure_months / (
            (1 + monthly_rate) ** tenure_months - 1
        )
    total_payment = emi * tenure_months
    total_interest = total_payment - principal

    def _inr_readable(val: float) -> str:
        """Format a number in Indian lakhs/crores for readability."""
        if val >= 1_00_00_000:
            return f"₹{val / 1_00_00_000:.2f} crore"
        elif val >= 1_00_000:
            return f"₹{val / 1_00_000:.2f} lakh"
        else:
            return f"₹{val:,.0f}"

    return {
        "loan_amount": _inr_readable(principal),
        "tenure": f"{tenure_years} years ({tenure_months} months)",
        "interest_rate": f"{annual_rate}%",
        "emi": round(emi, 2),
        "emi_readable": _inr_readable(emi),
        "total_payment": round(total_payment, 2),
        "total_payment_readable": _inr_readable(total_payment),
        "total_interest": round(total_interest, 2),
        "total_interest_readable": _inr_readable(total_interest),
    }


# ── Collateral / Property Assessment ──────────────────────────────────────────

# LTV ratios by property type and city tier (RBI-style guidelines)
# City tier is determined by the agent from city name + pin code — not hardcoded.
_LTV_MATRIX = {
    # (property_type, city_tier) → LTV ratio
    ("residential_apartment", "tier1"): 0.75,
    ("residential_apartment", "tier2"): 0.70,
    ("residential_apartment", "tier3"): 0.65,
    ("independent_house", "tier1"): 0.70,
    ("independent_house", "tier2"): 0.65,
    ("independent_house", "tier3"): 0.60,
    ("villa", "tier1"): 0.70,
    ("villa", "tier2"): 0.65,
    ("villa", "tier3"): 0.60,
    ("plot", "tier1"): 0.60,
    ("plot", "tier2"): 0.55,
    ("plot", "tier3"): 0.50,
    ("commercial", "tier1"): 0.60,
    ("commercial", "tier2"): 0.55,
    ("commercial", "tier3"): 0.50,
    ("under_construction", "tier1"): 0.70,
    ("under_construction", "tier2"): 0.65,
    ("under_construction", "tier3"): 0.60,
}


def assess_collateral(
    property_type: str,
    city: str,
    pin_code: str,
    city_tier: str,
    estimated_value_lakhs: float,
) -> dict:
    """
    Assess collateral for a home loan.
    city_tier is determined by the agent from city name + pin code.
    Accepts: 'tier1', 'tier2', or 'tier3'.
    Returns applicable LTV ratio and max eligible loan amount.
    """
    tier_key = city_tier.strip().lower().replace(" ", "")
    if tier_key in ("tier1", "metro"):
        tier_key = "tier1"
        tier_label = "Tier 1 (Metro)"
    elif tier_key in ("tier2",):
        tier_key = "tier2"
        tier_label = "Tier 2"
    else:
        tier_key = "tier3"
        tier_label = "Tier 3 / Rural"

    prop_key = property_type.strip().lower().replace(" ", "_")
    ltv = _LTV_MATRIX.get((prop_key, tier_key))
    if ltv is None:
        # Fallback: use conservative LTV
        ltv = 0.60
        prop_label = property_type.title()
    else:
        prop_label = property_type.replace("_", " ").title()

    estimated_value = estimated_value_lakhs * 1_00_000
    max_loan = estimated_value * ltv

    def _inr_readable(val: float) -> str:
        if val >= 1_00_00_000:
            return f"₹{val / 1_00_00_000:.2f} crore"
        elif val >= 1_00_000:
            return f"₹{val / 1_00_000:.2f} lakh"
        else:
            return f"₹{val:,.0f}"

    return {
        "property_type": prop_label,
        "city": city.strip().title(),
        "pin_code": pin_code.strip(),
        "city_tier": tier_label,
        "estimated_property_value": _inr_readable(estimated_value),
        "estimated_property_value_lakhs": estimated_value_lakhs,
        "ltv_ratio": ltv,
        "ltv_percentage": f"{int(ltv * 100)}%",
        "max_eligible_loan": _inr_readable(max_loan),
        "max_eligible_loan_lakhs": round(max_loan / 1_00_000, 2),
        "guideline": f"As per bank guidelines, for a {prop_label} in a {tier_label} city, we can finance up to {int(ltv * 100)}% of the property value.",
        "note": "Final loan amount subject to property valuation by our empanelled valuers and title verification.",
    }


def get_competitor_rates(product_name: str) -> dict:
    """Get competitor bank rates for a loan product for negotiation context."""
    rates = _query(
        "SELECT * FROM competitor_rates WHERE product_name = ?",
        (product_name,),
    )
    if not rates:
        return {"error": f"No competitor data for '{product_name}'"}

    rates_list = []
    for r in rates:
        rates_list.append({
            "bank": r["bank_name"],
            "min_rate": r["min_rate"],
            "max_rate": r["max_rate"],
            "processing_fee_pct": r["processing_fee_pct"],
        })

    min_market = min(r["min_rate"] for r in rates)
    max_market = max(r["max_rate"] for r in rates)

    return {
        "product": product_name,
        "competitor_rates": rates_list,
        "market_range_low": min_market,
        "market_range_high": max_market,
    }


# ─── Savings Agent Tools ─────────────────────────────────────────────────────

def get_account_details(customer_id: str) -> dict:
    """Savings/salary account details: balance, rate, min balance."""
    accounts = _query(
        "SELECT * FROM accounts WHERE customer_id = ?", (customer_id,)
    )
    return {"accounts": accounts}


def get_fixed_deposits(customer_id: str) -> dict:
    """All FDs: amount, rate, maturity, tax-saver flag."""
    fds = _query(
        "SELECT * FROM fixed_deposits WHERE customer_id = ?", (customer_id,)
    )
    return {"fixed_deposits": fds}


def get_recurring_deposits(customer_id: str) -> dict:
    """All RDs: monthly amount, rate, balance, maturity."""
    rds = _query(
        "SELECT * FROM recurring_deposits WHERE customer_id = ?",
        (customer_id,),
    )
    return {"recurring_deposits": rds}


def get_savings_transactions(customer_id: str) -> dict:
    """Recent savings account transactions (last 10)."""
    txns = _query(
        "SELECT date, description, amount, txn_type, category, balance_after "
        "FROM transactions "
        "WHERE customer_id = ? AND account_type = 'savings' "
        "ORDER BY date DESC LIMIT 10",
        (customer_id,),
    )
    return {"transactions": txns}


def get_fd_rate_card() -> dict:
    """Current FD rates by tenure — for advisory and comparison."""
    rates = _query("SELECT * FROM fd_rate_card ORDER BY min_days ASC")
    return {"fd_rates": rates}


# ─── General Banking Agent Tools ──────────────────────────────────────────────

def get_debit_card_details(customer_id: str) -> dict:
    """Debit card: network, type, daily limit, intl status."""
    cards = _query(
        "SELECT * FROM debit_cards WHERE customer_id = ?", (customer_id,)
    )
    return {"debit_cards": cards}


def get_investments(customer_id: str) -> dict:
    """All investments: MF, equity, PPF, NPS, Gold ETF."""
    inv = _query(
        "SELECT * FROM investments WHERE customer_id = ?", (customer_id,)
    )
    return {"investments": inv}


def get_all_transactions(customer_id: str) -> dict:
    """All recent transactions across savings + credit card (last 15)."""
    txns = _query(
        "SELECT account_type, date, description, amount, txn_type, category "
        "FROM transactions "
        "WHERE customer_id = ? "
        "ORDER BY date DESC LIMIT 15",
        (customer_id,),
    )
    return {"transactions": txns}


# ─── CIBIL Score Check (mock) ────────────────────────────────────────────────

def check_cibil_score(customer_id: str) -> dict:
    """
    Simulates a CIBIL bureau pull. Returns the customer's credit score,
    score band, key factors, and recent inquiry count.
    """
    customer = _query_one("SELECT * FROM customers WHERE id = ?", (customer_id,))
    if not customer:
        return {"error": "Customer not found"}

    cibil = customer.get("cibil_score", 0) or 0
    emi_delays = customer.get("emi_delays_12m", 0) or 0
    total_products = customer.get("total_products", 1) or 1

    # Determine score band
    if cibil >= 800:
        band = "Excellent"
    elif cibil >= 750:
        band = "Very Good"
    elif cibil >= 700:
        band = "Good"
    elif cibil >= 650:
        band = "Fair"
    else:
        band = "Poor"

    # Mock key factors
    factors = []
    if emi_delays == 0:
        factors.append("No missed payments in last 12 months")
    else:
        factors.append(f"{emi_delays} payment delay(s) in last 12 months")

    loans = _query(
        "SELECT COUNT(*) as count, SUM(outstanding) as total FROM loans WHERE customer_id = ? AND status = 'Active'",
        (customer_id,),
    )
    active_loans = loans[0]["count"] if loans else 0
    total_outstanding = loans[0]["total"] or 0 if loans else 0

    if active_loans <= 2:
        factors.append(f"Low credit utilization ({active_loans} active loans)")
    else:
        factors.append(f"Multiple active loans ({active_loans}) — moderate utilization")

    if total_products >= 3:
        factors.append(f"Healthy credit mix ({total_products} products)")

    monthly_income = customer.get("monthly_income", 0) or 0
    if monthly_income > 0 and total_outstanding > 0:
        dti = round((total_outstanding / (monthly_income * 12)) * 100, 1)
        factors.append(f"Debt-to-income ratio: {dti}%")

    return {
        "source": "CIBIL TransUnion",
        "report_date": "2026-06-01",
        "cibil_score": cibil,
        "score_band": band,
        "score_range": "300-900",
        "key_factors": factors,
        "active_accounts": active_loans,
        "total_outstanding": total_outstanding,
        "recent_inquiries_90d": 1 if active_loans > 0 else 0,
        "oldest_account_years": round(
            ((__import__("datetime").date.today() - __import__("datetime").date.fromisoformat(customer.get("relationship_since", "2020-01-01"))).days / 365.25), 1
        ),
    }


# ─── RBI Repo Rate Check (mock) ──────────────────────────────────────────────

def check_rbi_repo_rate() -> dict:
    """
    Returns the current RBI repo rate and related policy rates.
    Static mock values for the demo.
    """
    return {
        "source": "Reserve Bank of India",
        "as_of": "2026-06-16",
        "repo_rate": 5.25,
        "reverse_repo_rate": 3.35,
        "marginal_standing_facility_rate": 5.50,
        "bank_rate": 5.50,
        "crr": 4.0,
        "slr": 18.0,
        "last_change": {
            "date": "2025-12-05",
            "action": "Held steady (neutral stance)",
            "previous_rate": 5.25,
        },
        "next_mpc_meeting": "2026-08-05",
        "outlook": "Neutral — rate held to balance growth and inflation",
        "note": "Home loan rates typically benchmarked to repo rate. Current spread: 2.5-4.0% above repo.",
    }

# ─── Function dispatch map ────────────────────────────────────────────────────

TOOL_FUNCTIONS = {
    # Triage
    "get_customer_profile": get_customer_profile,
    "get_customer_summary": get_customer_summary,
    "get_eligibility_assessment": get_eligibility_assessment,
    # Credit Card
    "get_credit_card_details": get_credit_card_details,
    "get_credit_card_transactions": get_credit_card_transactions,
    "get_reward_points": get_reward_points,
    "get_card_spending_analysis": get_card_spending_analysis,
    "check_card_upgrade_eligibility": check_card_upgrade_eligibility,
    # Loan
    "get_active_loans": get_active_loans,
    "get_loan_product_details": get_loan_product_details,
    "get_preapproved_offers": get_preapproved_offers,
    "get_negotiation_terms": get_negotiation_terms,
    "calculate_emi": calculate_emi,
    "get_competitor_rates": get_competitor_rates,
    "assess_collateral": assess_collateral,
    # CIBIL & RBI
    "check_cibil_score": check_cibil_score,
    "check_rbi_repo_rate": check_rbi_repo_rate,
    # Savings
    "get_account_details": get_account_details,
    "get_fixed_deposits": get_fixed_deposits,
    "get_recurring_deposits": get_recurring_deposits,
    "get_savings_transactions": get_savings_transactions,
    "get_fd_rate_card": get_fd_rate_card,
    # General Banking
    "get_debit_card_details": get_debit_card_details,
    "get_investments": get_investments,
    "get_all_transactions": get_all_transactions,
}
