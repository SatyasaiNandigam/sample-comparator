"""
BRD schema registry – 43 properties across 7 groups for Business Requirements Document extraction.

Mirrors the structure of policy_schema.py but targets BRD-specific sections
(PROV-01…PROV-15 and CALC-001…CALC-013).  No existing files are modified.
"""
from __future__ import annotations

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from policy_schema import Property  # reuse the same frozen dataclass

VERSION = "0.1"

BRD_GROUPS = [
    "product_identity",
    "eligibility",
    "crediting",
    "withdrawals",
    "benefits",
    "calculations",
    "processing",
]


def BP(key, label, order, group, type_, description, compare="judge",
       aliases=(), not_=(), format_hint=None, na_means=None, notes=None) -> Property:
    return Property(
        key=key, label=label, order=order, group=group, type=type_,
        description=description, compare=compare,
        aliases=tuple(aliases), not_=tuple(not_),
        format_hint=format_hint, na_means=na_means, notes=notes,
    )


BRD_PROPERTIES: list[Property] = [

    # ─────────────────────────── product_identity ───────────────────────────── #
    BP("product_name", "Product Name", 1, "product_identity", "text",
       "Marketing or product name of the annuity contract as stated in the BRD.",
       compare="exact",
       aliases=["product name", "contract name", "annuity name"],
       notes="Extract from cover page or document header."),

    BP("product_type", "Product Type", 2, "product_identity", "enum_text",
       "Category of the annuity (e.g. Fixed Indexed Annuity, Multi-Year Guaranteed Annuity).",
       compare="exact",
       aliases=["annuity type", "contract type", "product category"],
       format_hint="short canonical label, e.g. 'Fixed Indexed Annuity'"),

    BP("issuing_company", "Issuing Company", 3, "product_identity", "text",
       "Name of the insurance company issuing the product as stated in the BRD.",
       compare="exact",
       aliases=["issuer", "carrier", "insurance company", "company name"]),

    BP("brd_version", "BRD Version / Date", 4, "product_identity", "date",
       "Version date or effective date of this BRD document.",
       compare="exact",
       aliases=["version date", "effective date", "document date", "as of date", "revision date"],
       format_hint="ISO date yyyy-mm-dd"),

    # ─────────────────────────────── eligibility ────────────────────────────── #
    BP("issue_ages", "Issue Age Limits", 5, "eligibility", "age_bands",
       "Minimum and maximum issue ages, by plan category (Qualified, Non-Qualified, etc.). "
       "Source: PROV-01.",
       compare="bands",
       aliases=["issue age", "age limits", "eligible ages", "maximum issue age"],
       format_hint="[{category, min_age, max_age}]"),

    BP("qualified_plan_types", "Qualified Plan Types", 6, "eligibility", "list_text",
       "Tax-qualification plan types the product supports (IRA, NQ, Roth IRA, SEP IRA, etc.). "
       "Source: PROV-01.",
       compare="set",
       aliases=["plan types", "eligible plans", "tax status", "market types"],
       format_hint="['IRA','NQ','Roth IRA','SEP IRA']"),

    BP("premium_bands", "Premium Band Thresholds", 7, "eligibility", "rate_band",
       "Premium band thresholds that affect rate or charge tiers. Source: PROV-02.",
       compare="bands",
       aliases=["premium bands", "rate bands", "band thresholds", "rate tier"],
       format_hint="{band: str, threshold: float}"),

    BP("state_availability", "State Availability", 8, "eligibility", "state_set",
       "US states where the product is available or not available. Source: PROV-01.",
       compare="set",
       aliases=["state availability", "states approved", "product availability by state"],
       format_hint="{mode: 'approved'|'not_approved', states: ['CA','NY']}"),

    # ──────────────────────────────── crediting ─────────────────────────────── #
    BP("goa_crediting_method", "GOA Crediting Method", 9, "crediting", "text",
       "Description of how interest is credited in the General Option Account (GOA). "
       "Source: PROV-03.",
       aliases=["GOA method", "general account crediting", "interest crediting method",
                "GOA interest"]),

    BP("goa_interest_timing", "GOA Interest Timing", 10, "crediting", "enum_text",
       "When GOA interest is credited (e.g. annually, daily, monthly). Source: PROV-03.",
       compare="exact",
       aliases=["interest timing", "crediting frequency", "GOA crediting timing"],
       format_hint="e.g. 'annually', 'daily', 'monthly'"),

    BP("foa_cap", "FOA Cap Percentage", 11, "crediting", "pct_formula",
       "Maximum participation cap for the Fixed Option Account (FOA). Source: PROV-04.",
       compare="numeric",
       aliases=["FOA cap", "fixed option cap", "allocation cap", "FOA maximum"],
       format_hint="{varies: bool, pct_of_premium: null, rate_min: float, rate_max: float}",
       notes="Use rate_min and rate_max for the cap range; pct_of_premium is null here."),

    BP("foa_reallocation_frequency", "FOA Reallocation Frequency", 12, "crediting", "enum_text",
       "How often the FOA allows reallocation of funds. Source: PROV-04.",
       compare="exact",
       aliases=["reallocation frequency", "FOA reallocation", "transfer frequency"],
       format_hint="e.g. 'annually', 'quarterly'"),

    BP("gop_renewal_terms", "GOP Renewal Terms", 13, "crediting", "text",
       "Terms and conditions for renewal of the Guaranteed Option Period (GOP). Source: PROV-05.",
       aliases=["GOP renewal", "renewal terms", "option period renewal",
                "guaranteed period renewal"]),

    # ──────────────────────────────── withdrawals ───────────────────────────── #
    BP("free_withdrawal_pct", "Free Withdrawal Percentage", 14, "withdrawals", "pct_formula",
       "Percentage of contract value or premium that may be withdrawn without charge each year. "
       "Source: PROV-06.",
       compare="numeric",
       aliases=["free withdrawal", "penalty-free withdrawal", "annual free withdrawal",
                "withdrawal allowance"],
       format_hint="{varies: bool, pct_of_premium: float|null, rate_min: float|null, "
                   "rate_max: float|null}"),

    BP("systematic_withdrawal_options", "Systematic Withdrawal Options", 15, "withdrawals",
       "list_text",
       "Available systematic withdrawal modes (e.g. RMD, fixed amount, fixed period). "
       "Source: PROV-06.",
       compare="set",
       aliases=["systematic withdrawals", "scheduled withdrawals", "withdrawal options"],
       format_hint="['Fixed Amount','Fixed Period','RMD','Interest Only']"),

    BP("rmd_handling", "RMD Handling", 16, "withdrawals", "text",
       "How the contract handles Required Minimum Distributions. Source: PROV-07.",
       aliases=["RMD", "required minimum distribution", "RMD rules"],
       na_means="Product does not address RMDs"),

    BP("sepp_handling", "SEPP Handling", 17, "withdrawals", "text",
       "How the contract handles Substantially Equal Periodic Payments (72(t)). Source: PROV-07.",
       aliases=["SEPP", "72(t)", "substantially equal periodic payments"],
       na_means="Product does not address SEPP"),

    BP("withdrawal_charge_schedule", "Withdrawal Charge Schedule", 18, "withdrawals", "schedule",
       "Year-by-year withdrawal (surrender) charge percentages. Source: PROV-08.",
       compare="schedule",
       aliases=["surrender charge", "withdrawal charge", "CDSC", "surrender charge schedule"],
       format_hint="{years: int, schedule_pct: [float per year], "
                   "mva: none|positive|negative|both|unspecified|null}",
       notes="Include trailing 0% year if shown. Record MVA applicability in the mva field."),

    BP("mva_conditions", "MVA Applicability Conditions", 19, "withdrawals", "text",
       "Conditions under which a Market Value Adjustment (MVA) applies or is waived. "
       "Source: PROV-08.",
       aliases=["MVA conditions", "market value adjustment", "MVA waiver",
                "MVA applicability"],
       na_means="No MVA applies"),

    BP("surrender_conditions", "Full Surrender Conditions", 20, "withdrawals", "text",
       "Conditions and rules governing full contract surrender and termination. Source: PROV-09.",
       aliases=["full surrender", "contract termination", "surrender rules",
                "surrender conditions"]),

    # ──────────────────────────────── benefits ──────────────────────────────── #
    BP("minimum_value_guarantee_rate", "Minimum Value Guarantee Rate", 21, "benefits",
       "pct_formula",
       "Guaranteed minimum interest rate used to compute the minimum contract value floor. "
       "Source: PROV-10.",
       compare="numeric",
       aliases=["minimum guaranteed rate", "floor rate", "MGSV rate",
                "minimum guarantee rate"],
       format_hint="{varies: bool, pct_of_premium: float|null, rate_min: float, "
                   "rate_max: float|null}"),

    BP("minimum_value_basis", "Minimum Value Basis", 22, "benefits", "enum_text",
       "The basis used to compute the minimum contract value (e.g. percentage of premiums paid, "
       "accumulated value). Source: PROV-10.",
       compare="exact",
       aliases=["minimum value basis", "MGSV basis", "guarantee basis"],
       format_hint="e.g. 'percentage of premiums paid', 'accumulated value'"),

    BP("death_benefit_type", "Death Benefit Type", 23, "benefits", "enum_text",
       "Type of death benefit provided (e.g. Account Value, Return of Premium, Stepped-Up). "
       "Source: PROV-11.",
       compare="exact",
       aliases=["death benefit", "death benefit type", "benefit on death"],
       format_hint="e.g. 'Account Value', 'Return of Premium'"),

    BP("death_benefit_continuation_options", "Death Benefit Continuation Options", 24, "benefits",
       "list_text",
       "Options available for the beneficiary to continue the contract instead of a lump sum. "
       "Source: PROV-11.",
       compare="set",
       aliases=["continuation options", "beneficiary options",
                "death benefit continuation"]),

    BP("annuitization_options", "Annuitization / Income Options", 25, "benefits", "list_text",
       "Available income or annuitization payout options (e.g. Life Only, Joint Life, "
       "Period Certain). Source: PROV-12.",
       compare="set",
       aliases=["annuitization options", "payout options", "income options",
                "annuity options"]),

    BP("maturity_age", "Maturity Age", 26, "benefits", "age_bands",
       "Age at which the contract matures or must annuitize. Source: PROV-12.",
       compare="bands",
       aliases=["maturity age", "maximum annuity date", "contract maturity"],
       format_hint="[{category: null, min_age: null, max_age: int}]"),

    BP("waiver_rider_eligibility", "Waiver Rider Eligibility", 27, "benefits", "text",
       "Eligibility criteria and benefit terms for available waiver riders. Source: PROV-13.",
       aliases=["waiver rider", "waiver of surrender charge", "disability waiver",
                "waiver terms"],
       na_means="No waiver riders available"),

    BP("contract_party_change_rules", "Contract-Party Change Rules", 28, "benefits", "text",
       "Rules governing changes to contract owner, annuitant, or beneficiary. Source: PROV-14.",
       aliases=["ownership change", "contract party change", "owner change",
                "beneficiary change"]),

    # ─────────────────────────────── calculations ───────────────────────────── #
    BP("compound_credited_value_formula", "Compound Credited Value Formula", 29,
       "calculations", "text",
       "Formula or method for computing the compound credited value. Source: CALC-001.",
       aliases=["compound credited value", "CALC-001"]),

    BP("simple_credited_value_formula", "Simple Credited Value Formula", 30,
       "calculations", "text",
       "Formula or method for computing the simple credited value and basis. Source: CALC-002.",
       aliases=["simple credited value", "CALC-002"]),

    BP("foa_value_formula", "FOA Value Formula", 31, "calculations", "text",
       "Formula or method for computing the FOA value. Source: CALC-003.",
       aliases=["FOA value", "CALC-003"]),

    BP("minimum_value_rate_formula", "Minimum Value Rate Formula", 32, "calculations", "text",
       "Formula for computing the minimum value rate. Source: CALC-004.",
       aliases=["minimum value rate", "CALC-004"]),

    BP("free_withdrawal_amount_formula", "Free Withdrawal Amount Formula", 33,
       "calculations", "text",
       "Formula for computing the free withdrawal amount. Source: CALC-006.",
       aliases=["free withdrawal amount", "CALC-006"]),

    BP("withdrawal_charge_formula", "Withdrawal Charge Formula", 34, "calculations", "text",
       "Formula for computing the withdrawal charge. Source: CALC-008.",
       aliases=["withdrawal charge formula", "CALC-008"]),

    BP("mva_factor_formula", "MVA Factor Formula", 35, "calculations", "text",
       "Formula for computing the Market Value Adjustment factor. Source: CALC-009.",
       aliases=["MVA factor", "CALC-009", "market value adjustment formula"]),

    BP("full_surrender_csv_formula", "Full Surrender MVA & CSV Formula", 36,
       "calculations", "text",
       "Formula for computing the cash surrender value under full surrender including MVA. "
       "Source: CALC-010.",
       aliases=["full surrender MVA", "CSV formula", "CALC-010"]),

    BP("partial_mva_proceeds_formula", "Partial MVA and Proceeds Formula", 37,
       "calculations", "text",
       "Formula for computing partial surrender proceeds including MVA. Source: CALC-011.",
       aliases=["partial MVA", "partial proceeds", "CALC-011"]),

    BP("death_benefit_formula", "Death Benefit Formula", 38, "calculations", "text",
       "Formula for computing the death benefit amount. Source: CALC-012.",
       aliases=["death benefit calculation", "CALC-012"]),

    BP("contract_income_formula", "Contract Income Value Formula", 39, "calculations", "text",
       "Formula for computing the contract income value. Source: CALC-013.",
       aliases=["contract income value", "income value formula", "CALC-013"]),

    # ──────────────────────────────── processing ────────────────────────────── #
    BP("transaction_processing_order", "Transaction Processing Order", 40, "processing",
       "list_text",
       "Ordered sequence in which transactions are processed within a business day. "
       "Source: Section 8.1.",
       compare="schedule",
       aliases=["processing order", "transaction sequence", "value-processing order"],
       notes="Preserve the order; this is a sequence, not a set."),

    BP("reconciliation_tolerances", "Reconciliation Tolerances", 41, "processing", "text",
       "Allowed rounding differences and reconciliation tolerance values. Source: Section 11.2.",
       aliases=["reconciliation tolerance", "rounding tolerance", "tolerance values"]),

    BP("open_decisions_count", "Open Decisions / Unresolved Items", 42, "processing", "text",
       "Number and nature of open decisions or unresolved source conflicts. Source: Section 12.",
       aliases=["open decisions", "unresolved items", "source conflicts"]),

    BP("acceptance_criteria", "Acceptance Criteria", 43, "processing", "text",
       "High-level acceptance criteria for the BRD. Source: Section 14.1.",
       aliases=["acceptance criteria", "acceptance conditions", "UAT criteria"]),
]

BRD_PROPERTIES.sort(key=lambda p: p.order)
BY_BRD_KEY: dict[str, Property] = {p.key: p for p in BRD_PROPERTIES}


def by_brd_group(group: str) -> list[Property]:
    """All BRD properties belonging to one extraction group, in layout order."""
    return [p for p in BRD_PROPERTIES if p.group == group]


def validate_brd() -> list[str]:
    errors: list[str] = []
    keys = [p.key for p in BRD_PROPERTIES]
    if len(keys) != len(set(keys)):
        errors.append("duplicate keys")
    orders = [p.order for p in BRD_PROPERTIES]
    if orders != list(range(1, len(BRD_PROPERTIES) + 1)):
        errors.append(f"orders must be 1..{len(BRD_PROPERTIES)}, got {orders}")
    for p in BRD_PROPERTIES:
        if p.group not in BRD_GROUPS:
            errors.append(f"{p.key}: unknown group {p.group!r}")
    for g in BRD_GROUPS:
        if not by_brd_group(g):
            errors.append(f"group {g} has no properties")
    return errors


if __name__ == "__main__":
    errs = validate_brd()
    if errs:
        print("INVALID:")
        for e in errs:
            print(" -", e)
        raise SystemExit(1)
    print(f"BRD Schema v{VERSION} OK: {len(BRD_PROPERTIES)} properties")
    for g in BRD_GROUPS:
        props = by_brd_group(g)
        print(f"  {g} ({len(props)}): " + ", ".join(p.key for p in props))
