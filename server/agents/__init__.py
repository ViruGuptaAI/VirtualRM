from .triage_agent import TRIAGE_PROMPT, ROUTE_TOOL
from .credit_card_agent import CREDIT_CARD_PROMPT, CREDIT_CARD_TOOLS
from .loan_agent import LOAN_PROMPT, LOAN_TOOLS
from .savings_agent import SAVINGS_PROMPT, SAVINGS_TOOLS
from .general_banking_agent import GENERAL_BANKING_PROMPT, GENERAL_BANKING_TOOLS

# ──────────────────────────────────────────────────────────────────────────────
# Agent registry — maps intent keys to specialist prompts and metadata
# ──────────────────────────────────────────────────────────────────────────────
AGENT_REGISTRY = {
    "triage": {
        "prompt": TRIAGE_PROMPT,
        "name": "Anika (Virtual RM)",
        "voice": "en-IN-Diya:DragonHDLatestNeural",
        "tools": [ROUTE_TOOL],
    },
    "credit_card": {
        "prompt": CREDIT_CARD_PROMPT,
        "name": "Meera (Credit Card Specialist)",
        "voice": "en-IN-Diya:DragonHDLatestNeural",
        "tools": CREDIT_CARD_TOOLS,
    },
    "loan": {
        "prompt": LOAN_PROMPT,
        "name": "Priya (Loan Specialist)",
        "voice": "en-IN-Diya:DragonHDLatestNeural",
        "tools": LOAN_TOOLS,
    },
    "savings_account": {
        "prompt": SAVINGS_PROMPT,
        "name": "Kavya (Savings Specialist)",
        "voice": "en-IN-Diya:DragonHDLatestNeural",
        "tools": SAVINGS_TOOLS,
    },
    "general_banking": {
        "prompt": GENERAL_BANKING_PROMPT,
        "name": "Riya (General Banking)",
        "voice": "en-IN-Diya:DragonHDLatestNeural",
        "tools": GENERAL_BANKING_TOOLS,
    },
}
