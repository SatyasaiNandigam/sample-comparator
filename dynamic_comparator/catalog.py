"""
Catalog transcribed from PropertiesInfo.jpeg: product categories, product types and the
17 "Business Provision Areas" per category, folded into stable property groups.
"""
from __future__ import annotations

# category slug -> display name
CATEGORY_NAMES = {
    "life": "Life Insurance",
    "annuity": "Annuity Insurance",
    "group": "Group Insurance",
}

# category slug -> {type slug: display name}
CATEGORIES: dict[str, dict[str, str]] = {
    "life": {
        "term": "Term Life",
        "whole_life": "Whole Life",
        "ul": "Universal Life (UL)",
        "vul": "Variable Universal Life (VUL)",
    },
    "annuity": {
        "fixed": "Fixed Annuity",
        "variable": "Variable Annuity",
        "indexed": "Indexed Annuity",
        "immediate": "Immediate Annuity",
        "deferred": "Deferred Annuity",
    },
    "group": {
        "group_life": "Group Life",
        "disability": "Group Disability",
        "health": "Group Health",
        "ad_and_d": "Group AD&D",
    },
}

# Provision area -> {category: text}. None = "Generally not applicable".
PROVISION_ROWS: dict[str, dict[str, str | None]] = {
    "Product Purpose": {
        "life": "Protection and wealth transfer",
        "annuity": "Retirement savings and income generation",
        "group": "Coverage for members/employees"},
    "Product Types": {
        "life": "Term, Whole Life, UL, VUL",
        "annuity": "Fixed, Variable, Indexed, Immediate, Deferred",
        "group": "Group Life, Disability, Health, AD&D"},
    "Eligibility Rules": {
        "life": "Age, underwriting, health factors",
        "annuity": "Age, suitability, funding requirements",
        "group": "Employer or association eligibility"},
    "Parties Involved": {
        "life": "Owner, Insured, Beneficiary",
        "annuity": "Owner, Annuitant, Beneficiary",
        "group": "Policyholder, Member, Beneficiary"},
    "Premium Requirements": {
        "life": "Level, Flexible, Single Premium",
        "annuity": "Single or Flexible Premium",
        "group": "Employer/Employee Contributions"},
    "Account Structure": {
        "life": "Face Amount + Cash Value",
        "annuity": "Accumulation/Contract Account",
        "group": "Certificate-based Coverage"},
    "Interest/Crediting": {
        "life": "Cash value growth",
        "annuity": "Fixed, Indexed or Variable growth",
        "group": None},
    "Policy Values": {
        "life": "Cash Value, Loan Value",
        "annuity": "Contract Value, Income Value",
        "group": "Coverage Amount"},
    "Withdrawals": {
        "life": "Loans, Partial Surrenders",
        "annuity": "Partial Withdrawals, Income Draws",
        "group": None},
    "Death Benefit": {
        "life": "Face Amount or Cash Value",
        "annuity": "Contract Value or Guaranteed Benefit",
        "group": "Coverage Amount"},
    "Living Benefits": {
        "life": "Critical Illness, LTC Riders",
        "annuity": "Income & LTC Riders",
        "group": "Disability and Health Benefits"},
    "Claims Processing": {
        "life": "Death Claims",
        "annuity": "Death and Income Claims",
        "group": "Member Claims"},
    "Policy Changes": {
        "life": "Beneficiary/Ownership Changes",
        "annuity": "Ownership and Income Elections",
        "group": "Enrollment Changes"},
    "Regulatory Requirements": {
        "life": "Life Regulations",
        "annuity": "Annuity Regulations",
        "group": "Group Insurance Regulations"},
    "Data Requirements": {
        "life": "Insured and Underwriting Data",
        "annuity": "Contract and Contribution Data",
        "group": "Employer and Member Data"},
    "Key Transactions": {
        "life": "Issue, Premium, Loan, Claim",
        "annuity": "Issue, Contribution, Withdrawal",
        "group": "Enrollment, Termination, Claim"},
    "Complexity": {
        "life": "Medium-High",
        "annuity": "High",
        "group": "Medium"},
}

# Stable property groups (order = layout order of generated properties).
DYNAMIC_GROUPS = [
    "product_info",
    "eligibility",
    "premiums",
    "crediting_values",
    "withdrawals_charges",
    "benefits",
    "servicing",
]

# Provision area -> group. "Complexity" is context only and has no group.
ROW_TO_GROUP: dict[str, str | None] = {
    "Product Purpose": "product_info",
    "Product Types": "product_info",
    "Parties Involved": "product_info",
    "Eligibility Rules": "eligibility",
    "Regulatory Requirements": "eligibility",
    "Premium Requirements": "premiums",
    "Account Structure": "premiums",
    "Interest/Crediting": "crediting_values",
    "Policy Values": "crediting_values",
    "Withdrawals": "withdrawals_charges",
    "Death Benefit": "benefits",
    "Living Benefits": "benefits",
    "Claims Processing": "servicing",
    "Policy Changes": "servicing",
    "Key Transactions": "servicing",
    "Data Requirements": "servicing",
    "Complexity": None,
}

# Product-type specific emphasis injected into the prompt.
TYPE_EMPHASIS: dict[tuple[str, str], str] = {
    ("life", "term"): "Level term period, renewability and convertibility. No cash value and no loans: "
                      "do not generate cash-value or crediting properties.",
    ("life", "whole_life"): "Guaranteed cash value, dividends (participating or not), paid-up additions, "
                            "policy loans, level premiums for life.",
    ("life", "ul"): "Flexible premiums, credited interest rate and minimum guarantee, cost of insurance and "
                    "expense charges, death benefit option A/B, surrender charges, loans and partial withdrawals.",
    ("life", "vul"): "Sub-account/fund options, separate account fees and M&E charges, investment risk, "
                     "cost of insurance, death benefit options, no-lapse guarantee riders.",
    ("annuity", "fixed"): "Declared fixed rate, guarantee period, minimum guaranteed value, surrender charge "
                          "schedule and MVA, free withdrawals. Same shape as the existing hardcoded annuity registry.",
    ("annuity", "variable"): "Sub-accounts, separate account and M&E fees, fund expenses, guaranteed living and "
                             "death benefit riders (GMWB, GMAB, GMIB, GMDB), investment risk.",
    ("annuity", "indexed"): "Index strategies, caps, participation rates, spreads, floors, crediting period, "
                            "strategy allocation, surrender charges, rider fees.",
    ("annuity", "immediate"): "Single premium, payout options (life only, joint, period certain), payout "
                              "frequency, income start date, COLA, no accumulation phase or surrender charge.",
    ("annuity", "deferred"): "Accumulation vs income phase, deferral period, annuitization date and options, "
                             "surrender charges, withdrawals before income start.",
    ("group", "group_life"): "Coverage amount as multiple of salary or flat, guarantee issue limits, "
                             "age reduction, conversion and portability, employee/dependent/AD&D coverage.",
    ("group", "disability"): "Elimination period, benefit period, benefit percentage and maximum, "
                             "own-occupation vs any-occupation definition, pre-existing condition limits, "
                             "short vs long term.",
    ("group", "health"): "Deductibles, copays, coinsurance, out-of-pocket maximum, network, "
                         "waiting period, dependent eligibility, COBRA.",
    ("group", "ad_and_d"): "Principal sum, accidental death and dismemberment schedule, exclusions, "
                           "24-hour vs occupational coverage, seat belt and other riders.",
}
