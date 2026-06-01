# ──────────────────────────────────────────────────────────────────────────────
# SOP Registry — Maps (agent, sub_intent) → (workflow text, required tool names)
# ──────────────────────────────────────────────────────────────────────────────
# At handoff, the triage agent provides both intent + sub_intent.
# The server looks up the right SOP, concatenates it with the lean base prompt,
# and filters tools to ONLY include what the SOP needs.
# This minimizes token usage per LLM call.
# ──────────────────────────────────────────────────────────────────────────────

from .loan_sops import (
    LOAN_STATUS,
    LOAN_RATE_REDUCTION,
    LOAN_NEW_INQUIRY,
    LOAN_FORECLOSURE,
    LOAN_BALANCE_TRANSFER,
    LOAN_EMI_RESTRUCTURE,
    LOAN_PREAPPROVED,
    LOAN_DEFAULT,
)
from .credit_card_sops import (
    CC_FEE_NEGOTIATION,
    CC_CANCELLATION,
    CC_UPGRADE,
    CC_DISPUTE,
    CC_REWARDS,
    CC_LIMIT_INCREASE,
    CC_DEFAULT,
)
from .savings_sops import (
    SAVINGS_FD_NEW,
    SAVINGS_FD_PREMATURE,
    SAVINGS_ACCOUNT_CLOSURE,
    SAVINGS_INVESTMENT,
    SAVINGS_RD_INQUIRY,
    SAVINGS_DEFAULT,
)
from .general_sops import (
    GENERAL_COMPLAINT,
    GENERAL_FRAUD,
    GENERAL_DEBIT_CARD,
    GENERAL_KYC,
    GENERAL_INVESTMENT,
    GENERAL_DEFAULT,
)


# (agent_key, sub_intent) → (SOP text, frozenset of required tool names)
SOP_REGISTRY: dict[tuple[str, str], tuple[str, frozenset[str]]] = {
    # ── Loan SOPs ─────────────────────────────────────────────────────
    ("loan", "loan_status"): (
        LOAN_STATUS,
        frozenset({"get_active_loans", "get_preapproved_offers", "get_negotiation_terms", "calculate_emi", "get_competitor_rates", "get_loan_product_details", "get_eligibility_assessment", "play_hold_music"}),
    ),
    ("loan", "rate_reduction"): (
        LOAN_RATE_REDUCTION,
        frozenset({"get_active_loans", "get_negotiation_terms", "calculate_emi", "get_competitor_rates", "get_eligibility_assessment", "play_hold_music", "check_cibil_score", "check_rbi_repo_rate"}),
    ),
    ("loan", "new_inquiry"): (
        LOAN_NEW_INQUIRY,
        frozenset({"get_preapproved_offers", "get_loan_product_details", "calculate_emi", "get_eligibility_assessment", "check_cibil_score", "check_rbi_repo_rate", "get_negotiation_terms", "get_competitor_rates", "play_hold_music"}),
    ),
    ("loan", "foreclosure"): (
        LOAN_FORECLOSURE,
        frozenset({"get_active_loans", "get_negotiation_terms", "calculate_emi"}),
    ),
    ("loan", "balance_transfer"): (
        LOAN_BALANCE_TRANSFER,
        frozenset({"get_negotiation_terms", "get_competitor_rates", "calculate_emi"}),
    ),
    ("loan", "emi_restructure"): (
        LOAN_EMI_RESTRUCTURE,
        frozenset({"get_active_loans", "calculate_emi"}),
    ),
    ("loan", "preapproved"): (
        LOAN_PREAPPROVED,
        frozenset({"get_preapproved_offers"}),
    ),

    # ── Credit Card SOPs ──────────────────────────────────────────────
    ("credit_card", "fee_waiver"): (
        CC_FEE_NEGOTIATION,
        frozenset({"get_credit_card_details", "get_card_spending_analysis"}),
    ),
    ("credit_card", "cancellation"): (
        CC_CANCELLATION,
        frozenset({"get_credit_card_details", "get_card_spending_analysis", "get_reward_points"}),
    ),
    ("credit_card", "upgrade"): (
        CC_UPGRADE,
        frozenset({"check_card_upgrade_eligibility", "get_card_spending_analysis"}),
    ),
    ("credit_card", "dispute"): (
        CC_DISPUTE,
        frozenset({"get_credit_card_details", "get_credit_card_transactions"}),
    ),
    ("credit_card", "rewards"): (
        CC_REWARDS,
        frozenset({"get_reward_points", "get_card_spending_analysis"}),
    ),
    ("credit_card", "limit_increase"): (
        CC_LIMIT_INCREASE,
        frozenset({"get_credit_card_details", "get_card_spending_analysis"}),
    ),

    # ── Savings SOPs ──────────────────────────────────────────────────
    ("savings_account", "fd_new"): (
        SAVINGS_FD_NEW,
        frozenset({"get_fd_rate_card", "get_fixed_deposits"}),
    ),
    ("savings_account", "fd_premature"): (
        SAVINGS_FD_PREMATURE,
        frozenset({"get_fixed_deposits", "get_fd_rate_card"}),
    ),
    ("savings_account", "account_closure"): (
        SAVINGS_ACCOUNT_CLOSURE,
        frozenset({"get_account_details", "get_fixed_deposits", "get_recurring_deposits"}),
    ),
    ("savings_account", "investment"): (
        SAVINGS_INVESTMENT,
        frozenset({"get_fixed_deposits", "get_recurring_deposits", "get_fd_rate_card", "get_account_details"}),
    ),
    ("savings_account", "rd_inquiry"): (
        SAVINGS_RD_INQUIRY,
        frozenset({"get_recurring_deposits", "get_fd_rate_card"}),
    ),

    # ── General Banking SOPs ──────────────────────────────────────────
    ("general_banking", "complaint"): (
        GENERAL_COMPLAINT,
        frozenset({"get_customer_profile", "get_all_transactions"}),
    ),
    ("general_banking", "fraud"): (
        GENERAL_FRAUD,
        frozenset({"get_debit_card_details", "get_all_transactions", "get_customer_profile"}),
    ),
    ("general_banking", "debit_card"): (
        GENERAL_DEBIT_CARD,
        frozenset({"get_debit_card_details", "get_customer_profile"}),
    ),
    ("general_banking", "kyc"): (
        GENERAL_KYC,
        frozenset({"get_customer_profile"}),
    ),
    ("general_banking", "investment"): (
        GENERAL_INVESTMENT,
        frozenset({"get_investments", "get_customer_profile"}),
    ),
}


# Default SOPs send ALL agent tools (no filtering)
DEFAULT_SOPS: dict[str, str] = {
    "loan":             LOAN_DEFAULT,
    "credit_card":      CC_DEFAULT,
    "savings_account":  SAVINGS_DEFAULT,
    "general_banking":  GENERAL_DEFAULT,
}


def get_sop(agent_key: str, sub_intent: str = "") -> tuple[str, frozenset[str] | None]:
    """
    Look up the right SOP for this agent + sub-intent.
    Returns (sop_text, required_tool_names).
    If tool_names is None, send ALL agent tools (default/fallback).
    """
    if sub_intent:
        entry = SOP_REGISTRY.get((agent_key, sub_intent))
        if entry:
            return entry  # (sop_text, tool_names)
    default_text = DEFAULT_SOPS.get(agent_key, "")
    return (default_text, None)  # None = send all agent tools
