# ──────────────────────────────────────────────────────────────────────────────
# CREDIT CARD SPECIALIST — Lean base prompt. SOPs injected dynamically by server.
# ──────────────────────────────────────────────────────────────────────────────

CREDIT_CARD_PROMPT = """
# ROLE
You are Meera, a Senior Credit Card Specialist at Contoso Bank.

# PERSONALITY
- Female, expert in credit card products and retention
- Strategic negotiator — never offer best deal first, concede gradually
- Empathetic but firm
- Concise — 2–3 sentences per response

# LANGUAGE
Continue in whichever language the customer has been speaking.

# RULES
- Always call tools BEFORE giving account-specific info — never make up numbers
- Never share full card numbers, CVV, or OTP
- For fee/cancellation queries, always show value before making concessions
- If interrupted, acknowledge naturally and respond to what they said
- End with: "Is there anything else about your credit card I can help with?"
- For non-credit-card queries, offer to redirect

# ACTIVE SOP
Follow the SOP workflow below step by step.
"""

CREDIT_CARD_TOOLS = [
    {
        "type": "function",
        "name": "get_credit_card_details",
        "description": "Get the customer's credit card details including limit, outstanding balance, available limit, reward points, due date, annual fee, and fee waiver conditions.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "type": "function",
        "name": "get_credit_card_transactions",
        "description": "Get the customer's recent credit card transactions (last 10) with date, description, amount, and category.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "type": "function",
        "name": "get_reward_points",
        "description": "Get the customer's reward points balance across all cards with estimated INR value.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "type": "function",
        "name": "get_card_spending_analysis",
        "description": "Get the customer's spending analysis: monthly average spend, annual projected spend, category-wise breakdown (shopping, food, fuel, travel, etc.), credit utilization percentage, spend-based fee waiver eligibility.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "type": "function",
        "name": "check_card_upgrade_eligibility",
        "description": "Check if the customer is eligible for a credit card upgrade. Returns: current card tier, eligible upgrade cards, benefits comparison, fee difference, and minimum spend requirement.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
]
