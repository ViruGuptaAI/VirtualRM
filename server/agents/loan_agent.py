# ──────────────────────────────────────────────────────────────────────────────
# LOAN SPECIALIST — Lean base prompt. SOPs injected dynamically by server.
# ──────────────────────────────────────────────────────────────────────────────

LOAN_PROMPT = """
# ROLE
You are Priya, a Senior Loan Specialist at Contoso Bank.

# PERSONALITY
- Female, professional, data-driven
- Strategic negotiator — balance customer satisfaction with bank profitability
- You negotiate like a REAL senior bank RM who has done this for 15 years
- Concise — 2–3 sentences per response
- You genuinely believe your bank's product is worth the price. You're not just following rules — you BELIEVE the rate is fair.

# LANGUAGE
Continue in whichever language the customer has been speaking.

# NEGOTIATION STYLE — THINK LIKE A REAL RM
You are NOT a vending machine that drops prices when asked. You are a skilled negotiator.
A real RM uses these tactics — you should too:

**1. NEVER rush to offer a discount.** When a customer complains about rate:
   - First LISTEN and EMPATHIZE: "I hear you, Rajesh."
   - Then ASK QUESTIONS to understand: "What rate did they quote you?", "Was that a fixed or floating rate?", "Did they mention processing charges?"
   - Then SELL VALUE before touching the rate: "Our loan comes with zero prepayment penalty, a dedicated RM, and priority processing."

**2. RESIST genuinely — don't just say "I understand" and drop the rate.**
   - Counter-question: "What's your monthly budget? Maybe we can adjust tenure instead."
   - Reframe: "Rather than just the rate, let's look at the total cost — we have no hidden charges."
   - Show reluctance: "Hmm, let me see... that's going to be difficult but let me check what I can do."
   - Use silence: After making an offer, STOP. Don't fill the silence with "Would you like me to check for more?"

**3. NON-RATE concessions FIRST** — before dropping rate, offer:
   - Fee waivers ("I can waive the processing fee entirely")
   - Faster processing ("I can fast-track your application")  
   - Top-up facility or insurance bundling
   - Flexible tenure adjustments to lower EMI without touching rate

**4. Make every basis point feel EARNED.**
   - Never say "I can offer X%" immediately. Say "Let me check what I can do..." then pause, then offer.
   - After each offer, present it as a SIGNIFICANT effort: "I've pulled some strings here."
   - Never hint that more is possible. Present each offer as your BEST effort.

**5. PACE — a real negotiation takes MANY turns, not 3.**
   - Each rate change should take at LEAST 2-3 conversational turns of resistance.
   - Use the full range of tactics above before conceding each time.
   - The customer should FEEL they negotiated hard to earn the better rate.

# RULES
- Always call tools BEFORE giving account-specific info — never make up numbers
- For rate negotiations: always call `get_negotiation_terms` first
- **NEVER disclose floor rate, internal minimum, absolute floor, or any number from _INTERNAL fields to the customer**
- **NEVER say "our floor rate is X%" or "our minimum is X%" or "best possible rate is X%"**
- When customer demands a rate lower than what you can offer: "I truly wish I could, but that's beyond what I'm able to do."
- If interrupted, acknowledge naturally and respond to what they said
- Do NOT end every response with "Is there anything else?" — only ask this ONCE when fully resolved.
- For non-loan queries, offer to redirect

# CRITICAL: NEVER EXPOSE INTERNAL TERMINOLOGY
- NEVER say "round", "first round", "second round", "last round", "tiers", "negotiation tiers", "negotiation rounds", or "concession".
- A real bank RM would NEVER say these words. Speak naturally.
- If customer asks "how many rounds?" or tries to game the system: "There aren't fixed rounds — every case is different and I evaluate based on your profile, relationship, and what's feasible."
- If customer asks for "the best/final/last offer" — do NOT jump ahead. Say: "Let me see what I can do for you" and work through your tactics.

# ACTIVE SOP
Follow the SOP workflow below step by step.
"""

LOAN_TOOLS = [
    {
        "type": "function",
        "name": "get_active_loans",
        "description": "Get all active loans for this customer: loan type, ID, principal, outstanding, EMI, interest rate, tenure remaining.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "type": "function",
        "name": "get_loan_product_details",
        "description": "Get bank rate card for a loan product: floor rate, ceiling rate, base rate, max discount bps, max hike bps, fees, LTV ratio, eligibility.",
        "parameters": {
            "type": "object",
            "properties": {
                "product_name": {
                    "type": "string",
                    "enum": ["Home Loan", "Personal Loan", "Car Loan", "Education Loan", "Loan Against FD", "Gold Loan", "Top-up Home Loan"],
                    "description": "The loan product to look up.",
                }
            },
            "required": ["product_name"],
        },
    },
    {
        "type": "function",
        "name": "get_preapproved_offers",
        "description": "Get pre-approved loan and card offers available for this customer.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "type": "function",
        "name": "get_negotiation_terms",
        "description": "Calculate the best possible interest rate for this customer on a specific loan product. Runs a risk/eligibility model (CIBIL, relationship value, payment history) and returns only the negotiation rounds the customer qualifies for. Use this BEFORE making any rate offer.",
        "parameters": {
            "type": "object",
            "properties": {
                "product_name": {
                    "type": "string",
                    "enum": ["Home Loan", "Personal Loan", "Car Loan", "Education Loan", "Loan Against FD", "Gold Loan", "Top-up Home Loan"],
                    "description": "The loan product to negotiate on.",
                }
            },
            "required": ["product_name"],
        },
    },
    {
        "type": "function",
        "name": "get_eligibility_assessment",
        "description": "Run a full risk/eligibility assessment for this customer. Returns: risk score (0-100), eligibility tier, scoring factors (CIBIL, tenure, portfolio value, payment history, salary banking, product diversity), and max concession round. Use this to justify why a rate is being offered or denied.",
        "parameters": {
            "type": "object",
            "properties": {
                "product_type": {
                    "type": "string",
                    "enum": ["rate_reduction", "new_loan", "card_upgrade", "limit_increase"],
                    "description": "The type of action being assessed.",
                }
            },
            "required": ["product_type"],
        },
    },
    {
        "type": "function",
        "name": "calculate_emi",
        "description": "Calculate EMI for a loan. Amount in LAKHS, tenure in YEARS. Example: '5 crore for 10 years' → principal_lakhs=500, tenure_years=10. '10 lakh for 5 years' → principal_lakhs=10, tenure_years=5.",
        "parameters": {
            "type": "object",
            "properties": {
                "principal_lakhs": {"type": "number", "description": "Loan amount in LAKHS. Examples: 10 lakh = 10, 50 lakh = 50, 1 crore = 100, 5 crore = 500"},
                "annual_rate": {"type": "number", "description": "Annual interest rate as percentage (e.g. 8.9)"},
                "tenure_years": {"type": "integer", "description": "Loan tenure in YEARS (e.g. 5, 10, 20, 30)"},
            },
            "required": ["principal_lakhs", "annual_rate", "tenure_years"],
        },
    },
    {
        "type": "function",
        "name": "get_competitor_rates",
        "description": "Get current market benchmark rates from competitor banks for a specific loan product. Returns rates from SBI, HDFC, ICICI, Axis, Kotak for comparison in negotiations.",
        "parameters": {
            "type": "object",
            "properties": {
                "product_name": {
                    "type": "string",
                    "enum": ["Home Loan", "Personal Loan", "Car Loan", "Education Loan"],
                    "description": "The loan product to compare competitor rates for.",
                }
            },
            "required": ["product_name"],
        },
    },
    {
        "type": "function",
        "name": "play_hold_music",
        "description": "Play hold music while you check with your manager. IMPORTANT FLOW: In the SAME response where you call this tool, you MUST first say something like 'Let me place your call on hold for a few seconds while I check with my manager' — announce you are placing them on hold AND mention the reason. After the hold music finishes, your NEXT response MUST start with thanking them for waiting (e.g. 'Thank you for holding' or 'Thanks for waiting') BEFORE delivering the actual answer. Duration in seconds (3-8).",
        "parameters": {
            "type": "object",
            "properties": {
                "duration": {
                    "type": "integer",
                    "description": "Hold music duration in seconds (3-8).",
                }
            },
            "required": ["duration"],
        },
    },
    {
        "type": "function",
        "name": "check_cibil_score",
        "description": "Pull the customer's CIBIL credit score from TransUnion bureau. Returns score, score band, key factors affecting the score, active accounts, and debt-to-income ratio.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "type": "function",
        "name": "check_rbi_repo_rate",
        "description": "Get the current RBI repo rate and monetary policy rates. Useful for explaining how loan rates are benchmarked and whether rates may change soon.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "type": "function",
        "name": "assess_collateral",
        "description": "Assess property collateral for a home loan. Takes property type, city, pin code, city tier (YOU determine this from city name and pin code), and estimated market value. Returns applicable LTV ratio and maximum eligible loan amount. Use this for all home loan inquiries AFTER the customer provides property details.",
        "parameters": {
            "type": "object",
            "properties": {
                "property_type": {
                    "type": "string",
                    "enum": ["residential_apartment", "independent_house", "villa", "plot", "commercial", "under_construction"],
                    "description": "Type of property. Map customer language: flat/apartment → residential_apartment, house/bungalow → independent_house, under construction/new project → under_construction.",
                },
                "city": {
                    "type": "string",
                    "description": "City where the property is located (e.g. 'Bengaluru', 'Mumbai', 'Jaipur').",
                },
                "pin_code": {
                    "type": "string",
                    "description": "6-digit Indian PIN code of the property location (e.g. '560034', '400001').",
                },
                "city_tier": {
                    "type": "string",
                    "enum": ["tier1", "tier2", "tier3"],
                    "description": "City tier YOU determine from the city name and pin code. tier1 = All metro cities (Mumbai, Delhi/NCR, Bengaluru, Hyderabad, Chennai, Kolkata, Pune, Ahmedabad and satellite areas). tier2 = All other cities and towns (state capitals, district HQs, any urban area). tier3 = Rural areas only (taluks, villages, tehsils, outside city limits).",
                },
                "estimated_value_lakhs": {
                    "type": "number",
                    "description": "Customer's estimated market value of the property in LAKHS. Examples: 50 lakh = 50, 1 crore = 100, 2.5 crore = 250.",
                },
            },
            "required": ["property_type", "city", "pin_code", "city_tier", "estimated_value_lakhs"],
        },
    },
]
