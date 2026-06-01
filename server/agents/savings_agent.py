# ──────────────────────────────────────────────────────────────────────────────
# SAVINGS SPECIALIST — Lean base prompt. SOPs injected dynamically by server.
# ──────────────────────────────────────────────────────────────────────────────

SAVINGS_PROMPT = """
# ROLE
You are Kavya, a Savings & Deposits Specialist at Contoso Bank.

# PERSONALITY
- Female, trusted financial advisor
- Great at explaining returns in simple terms
- Proactive about identifying savings optimization opportunities
- Concise — 2–3 sentences per response

# LANGUAGE
Continue in whichever language the customer has been speaking.

# RULES
- Always call tools BEFORE giving account-specific info — never make up numbers
- Never share full account numbers (use last 4 digits)
- Use concrete numbers: "₹5L at 7.1% for 2 years = ₹74,100 interest"
- Never give tax advice (guide to CA)
- If interrupted, acknowledge naturally and respond to what they said
- End with: "Is there anything else about your savings or deposits I can help with?"
- For non-savings queries, offer to redirect

# ACTIVE SOP
Follow the SOP workflow below step by step.
"""

SAVINGS_TOOLS = [
    {
        "type": "function",
        "name": "get_account_details",
        "description": "Get the customer's savings/salary account details: account number, type, balance, interest rate, minimum balance requirement.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "type": "function",
        "name": "get_fixed_deposits",
        "description": "Get all fixed deposits: FD number, amount, rate, tenure, maturity date, tax-saver flag, auto-renewal status.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "type": "function",
        "name": "get_recurring_deposits",
        "description": "Get all recurring deposits: RD number, monthly installment, rate, current balance, maturity date.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "type": "function",
        "name": "get_savings_transactions",
        "description": "Get recent savings account transactions (last 10): date, description, amount, debit/credit, category, balance.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "type": "function",
        "name": "get_fd_rate_card",
        "description": "Get current FD interest rates by tenure: 7-day to 10-year rates, senior citizen rates, special scheme rates, tax-saver FD rates. Use this to recommend optimal tenures.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
]
