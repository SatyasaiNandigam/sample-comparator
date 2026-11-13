"""
Enriched schema registry for policy specification comparison (v0.1).

- 38 properties, in the same order as the target side-by-side layout.
- Schema is the single source of truth: drives prompts, normalizers, comparators.
- Adding a property = adding one entry here, no pipeline code changes.

Run `python policy_schema.py` to validate the registry.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional

VERSION = "0.1"

# --------------------------------------------------------------------------- #
# Controlled vocabularies
# --------------------------------------------------------------------------- #
GROUPS = [
    "product_info",
    "charges",
    "rates",
    "benefits",
    "availability",
    "compensation",
]

# Drives the normalizer (code) and the output shape asked from the LLM.
TYPES = {
    "text",                 # free text, kept as-is
    "enum_text",            # short label, canonicalized (e.g. "MYG Fixed")
    "date",                 # normalized to ISO yyyy-mm-dd
    "list_text",            # list of short items, compared as a set
    "currency",             # single amount
    "currency_by_category", # amount per category, e.g. Q/NQ -> $10,000
    "schedule",             # surrender-style year-by-year percentages
    "age_bands",            # ranges by age, optionally by category/year
    "state_set",            # set of US states (mode: approved | not_approved)
    "rate_by_term",         # rate(s) with a guarantee term
    "count_pair",           # e.g. "0 Indexed, 1 Fixed"
    "pct_formula",          # e.g. "87.5% @ 1-3%"
    "rate_band",            # e.g. "Low Band / $100,000"
}

COMPARE = {
    "exact",     # normalized equality
    "numeric",   # numeric equality with tolerance
    "set",       # set equality / set difference
    "schedule",  # element-wise list comparison
    "bands",     # interval-by-interval comparison
    "by_key",    # per-category comparison (Q vs NQ, etc.)
    "judge",     # LLM judge, only after deterministic checks fail
}

STATES = ["found", "not_applicable", "not_found"]


# --------------------------------------------------------------------------- #
# Property definition
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Property:
    key: str
    label: str
    order: int
    group: str
    type: str
    description: str
    compare: str
    aliases: tuple[str, ...] = ()
    not_: tuple[str, ...] = ()          # sibling keys this property must NOT capture
    format_hint: Optional[str] = None
    na_means: Optional[str] = None      # what "N/A" means for this property
    notes: Optional[str] = None         # extra guidance for the extraction prompt

    def to_dict(self) -> dict:
        d = asdict(self)
        d["not"] = list(d.pop("not_"))
        d["aliases"] = list(d["aliases"])
        return d


def P(key, label, order, group, type, description, compare, aliases=(), not_=(),
      format_hint=None, na_means=None, notes=None) -> Property:
    return Property(
        key=key, label=label, order=order, group=group, type=type,
        description=description, compare=compare, aliases=tuple(aliases),
        not_=tuple(not_), format_hint=format_hint, na_means=na_means, notes=notes,
    )


# --------------------------------------------------------------------------- #
# Registry (38 properties)
# --------------------------------------------------------------------------- #
PROPERTIES: list[Property] = [
    # ---------------------------- product_info ------------------------------ #
    P("company", "Company", 1, "product_info", "text",
      "Name of the issuing insurance company and, if stated, its parent group.",
      "exact",
      aliases=["issuer", "insurer", "carrier", "issued by", "insurance company"],
      format_hint="issuer name; if a parent group is stated append it after ' | ', e.g. 'Forethought Life Insurance Company | Global Atlantic Financial Group Limited'"),

    P("am_best_rating", "A.M Best Rating", 2, "product_info", "enum_text",
      "Financial strength rating of the issuer from A.M. Best (e.g. A, A+, A-).",
      "exact",
      aliases=["AM Best", "A.M. Best rating", "AMB rating", "financial strength rating"],
      format_hint="rating letter(s) only, e.g. 'A'",
      notes="Only the A.M. Best rating. Do not return S&P, Moody's or Fitch."),

    P("sp_rating", "Standard and Poor's Rating", 3, "product_info", "enum_text",
      "Financial strength rating of the issuer from Standard & Poor's (e.g. A, A+, AA-).",
      "exact",
      aliases=["S&P", "S&P rating", "Standard & Poor's", "S and P rating"],
      format_hint="rating letter(s) only, e.g. 'A'",
      notes="Only the S&P rating. Do not return A.M. Best, Moody's or Fitch."),

    P("product_type", "Product Type", 4, "product_info", "enum_text",
      "Category of the annuity product (e.g. MYG Fixed, Fixed Indexed, Variable, SPIA).",
      "exact",
      aliases=["annuity type", "contract type", "product category", "product class",
               "multi-year guaranteed annuity", "MYGA"],
      format_hint="short canonical label, e.g. 'MYG Fixed'"),

    P("primary_product_objective", "Primary Product Objective", 5, "product_info", "enum_text",
      "Main purpose the product is designed for (e.g. Accumulation, Income, Legacy).",
      "exact",
      aliases=["product objective", "purpose", "intended use", "product purpose",
               "primary purpose", "client objective"],
      format_hint="one word/phrase, e.g. 'Accumulation'"),

    P("product", "Product", 6, "product_info", "text",
      "Marketing/product name of the annuity, including the contract type in brackets if given.",
      "exact",
      aliases=["product name", "plan name", "contract name", "annuity name"],
      format_hint="product name; append the contract type in brackets if stated, e.g. 'SecureFore 3 Fixed Annuity (SPDA)'"),

    P("policy_form_number", "Policy Form Number", 7, "product_info", "text",
      "Form or contract identifier of the policy, including any state/series prefix.",
      "exact",
      aliases=["form number", "contract form", "policy form", "form no.", "contract form number",
               "contract number"],
      format_hint="identifier string, e.g. 'FA1101SPDA-01'",
      notes="Return the identifier exactly as printed, keep prefixes and suffixes."),

    P("distribution_channels", "Distribution Channels Sold In", 8, "product_info", "list_text",
      "Distribution channels through which the product is sold.",
      "set",
      aliases=["channels", "sold through", "distribution", "marketing channels",
               "broker-dealer", "bank channel", "independent channel"],
      format_hint="list of channel names, e.g. ['B/D: Full Service National', 'Bank', 'Independent']"),

    P("product_launch_date", "Product Launch Date", 9, "product_info", "date",
      "Date the product was first made available for sale.",
      "exact",
      aliases=["launch date", "effective date", "release date", "available since",
               "date introduced", "product effective date", "issue date of form"],
      format_hint="ISO date yyyy-mm-dd",
      notes="Not the date of this document and not the policy issue date."),

    # -------------------------------- charges ------------------------------- #
    P("bonus", "Bonus", 10, "charges", "text",
      "Premium or purchase bonus credited to the contract, with amount/percentage and vesting if stated.",
      "judge",
      aliases=["premium bonus", "purchase bonus", "initial bonus", "bonus credit",
               "bonus rate"],
      na_means="Product has no bonus"),

    P("surrender_charge", "Surrender Charge", 11, "charges", "schedule",
      "Surrender charge period in years and the charge percentage applied in each policy year. "
      "Also record whether a Market Value Adjustment (MVA) applies.",
      "schedule",
      aliases=["withdrawal charge", "CDSC", "contingent deferred sales charge",
               "surrender charge schedule", "early withdrawal charge", "surrender penalty"],
      format_hint="{years: int, schedule_pct: [float per year], mva: none|positive|negative|both|unspecified|null}",
      notes="Policy years run in order; the last 0% year ends the period. "
            "MVA belongs to this property, not to product_fee or other_charge."),

    P("product_fee", "Product Fee", 12, "charges", "text",
      "Recurring or one-time fee charged for the product itself, as amount or percentage.",
      "judge",
      aliases=["product charge", "contract fee", "policy fee", "administrative fee", "fee"],
      not_=["surrender_charge", "annual_contract_fee", "total_annual_expense", "other_charge"],
      na_means="Product has no product fee"),

    P("other_charge", "Other Charge", 13, "charges", "text",
      "Any charge or deduction that is NOT captured by another charge property "
      "(excludes surrender charge, MVA, product fee, annual contract fee and rider charges).",
      "judge",
      aliases=["additional charges", "other fees", "miscellaneous charges", "other deductions"],
      not_=["surrender_charge", "product_fee", "annual_contract_fee",
            "total_annual_expense", "annual_contract_fee_waived_at"],
      na_means="Document states no other charges apply",
      notes="Never return 'N/A' unless the document says no other charges exist. "
            "If no unrelated charge is described, state 'not_found'."),

    P("total_annual_expense", "*Total Annual Expense", 14, "charges", "text",
      "Total annual expense of the contract expressed as a percentage or amount. "
      "Excludes any rider charges.",
      "judge",
      aliases=["total expense ratio", "annual expense", "total annual charges",
               "TAE", "total contract expense"],
      not_=["product_fee", "annual_contract_fee", "other_charge"],
      na_means="No ongoing annual expenses",
      notes="Label carries a footnote: excludes rider charges."),

    P("annual_contract_fee", "Annual Contract Fee", 15, "charges", "currency",
      "Flat annual maintenance/contract fee charged to the contract, in dollars.",
      "numeric",
      aliases=["annual maintenance fee", "contract maintenance charge", "annual policy fee",
               "annual administrative fee", "policy fee"],
      not_=["product_fee", "total_annual_expense", "other_charge"],
      na_means="No annual contract fee",
      format_hint="dollar amount as a number"),

    P("annual_contract_fee_waived_at", "Annual Contract Fee Waived At", 16, "charges", "currency",
      "Contract value (or premium) at or above which the annual contract fee is waived.",
      "numeric",
      aliases=["fee waived at", "waiver threshold", "annual fee waived", "fee waiver amount",
               "contract fee waiver"],
      na_means="Not applicable, usually because no annual contract fee exists",
      format_hint="dollar threshold as a number; basis = what it is measured on (contract value or premium) if stated"),

    P("min_guarantee_msv", "Minimum Guarantee/ Minimum Guaranteed Surrender Value", 17,
      "charges", "pct_formula",
      "Minimum guaranteed contract (surrender) value: percentage of premium accumulated at a "
      "minimum guaranteed interest rate (e.g. 87.5% of premium at 1-3%).",
      "exact",
      aliases=["minimum guaranteed contract value", "minimum guaranteed surrender value",
               "MGSV", "nonforfeiture", "standard nonforfeiture", "minimum guaranteed value"],
      format_hint="pct_of_premium e.g. 87.5; rate_min/rate_max in percent e.g. 1 and 3; varies=true if stated as varying",
      notes="If the document says the value varies by state, return 'Varies' as raw_value "
            "and the formula separately when given."),

    # --------------------------------- rates -------------------------------- #
    P("strategies_offered", "Strategies Offered", 18, "rates", "count_pair",
      "Number of crediting strategies offered, split into indexed and fixed.",
      "exact",
      aliases=["crediting strategies", "interest crediting options", "allocation options",
               "number of strategies", "index options", "fixed account options"],
      format_hint="{indexed: int, fixed: int}",
      notes="Count strategies; do not copy their names."),

    P("rate_banding", "Rate Banding", 19, "rates", "rate_band",
      "Premium band the quoted rates apply to, as band name and dollar threshold.",
      "exact",
      aliases=["premium bands", "rate bands", "band", "rate tier", "premium tier",
               "high band", "low band"],
      format_hint="{band: str, threshold: float|null}  e.g. 'Low Band', 100000"),

    P("current_fixed_rates", "Current Fixed Account Rate(s)", 20, "rates", "rate_by_term",
      "Currently declared fixed interest rate(s) and how long they are guaranteed. "
      "Record each rate if more than one (e.g. base rate and bonus/enhanced rate).",
      "numeric",
      aliases=["current interest rate", "declared rate", "current rate", "initial rate",
               "guaranteed interest rate", "credited rate", "current crediting rate"],
      not_=["upcoming_fixed_rates", "other_crediting_strategy_info"],
      format_hint="{rates_pct: [float], guarantee_years: int|null}"),

    P("upcoming_fixed_rates", "Upcoming Fixed Account Rate(s)", 21, "rates", "rate_by_term",
      "Fixed interest rate(s) announced for a future effective date, not yet in force.",
      "numeric",
      aliases=["future rate", "next rate", "renewal rate", "scheduled rate change",
               "announced rate", "rate effective"],
      not_=["current_fixed_rates", "other_crediting_strategy_info"],
      na_means="No upcoming rate change announced",
      format_hint="{rates_pct: [float], effective_date: date|null, guarantee_years: int|null}"),

    P("other_crediting_strategy_info", "Other Crediting Strategy Information", 22, "rates", "text",
      "Crediting details beyond the current and upcoming fixed rates "
      "(indexed strategies, caps, spreads, participation rates, interest-rate renewal rules).",
      "judge",
      aliases=["additional crediting information", "crediting method details",
               "index strategy details", "caps and participation", "renewal rate method"],
      not_=["current_fixed_rates", "upcoming_fixed_rates", "strategies_offered", "rate_banding"],
      na_means="No other crediting strategy information"),

    # ------------------------------- benefits ------------------------------- #
    P("penalty_free_withdrawals", "Penalty-Free Withdrawals", 23, "benefits", "text",
      "Amount that may be withdrawn without surrender charge or MVA, and when it is available.",
      "judge",
      aliases=["free withdrawal", "free withdrawal provision", "free partial withdrawal",
               "withdrawal privilege", "penalty free withdrawal", "annual free withdrawal"],
      not_=["surrender_charge_waivers"],
      format_hint="one short phrase: percentage, basis and timing, e.g. '10% of premiums paid, immediately'",
      na_means="No penalty-free withdrawals"),

    P("death_benefit", "Death Benefit", 24, "benefits", "text",
      "Amount paid to beneficiaries on death of the owner/annuitant (e.g. Full Account Value).",
      "judge",
      aliases=["death benefit amount", "benefit on death", "death proceeds",
               "death benefit payable", "payable at death"],
      not_=["gmdb"],
      notes="Base death benefit only. Guaranteed minimum death benefit rider goes to gmdb."),

    P("surrender_charge_waivers", "Surrender Charge Waivers Available", 25, "benefits", "list_text",
      "Events that waive the surrender charge (e.g. Nursing Home, Terminal Illness, Critical "
      "Illness, Chronic Illness).",
      "set",
      aliases=["waiver of surrender charge", "surrender charge waiver", "withdrawal charge waiver",
               "nursing home waiver", "terminal illness waiver", "confinement waiver",
               "hardship waiver"],
      not_=["penalty_free_withdrawals"],
      format_hint="list of canonical event names: Nursing Home, Terminal Illness, "
                  "Critical Illness, Chronic Illness, Disability, Unemployment, ...",
      na_means="No surrender charge waivers"),

    P("glwb", "Guaranteed Lifetime Withdrawal Benefit (GLWB)", 30, "benefits", "text",
      "Rider guaranteeing lifetime withdrawals (GLWB), with charge and key terms if stated.",
      "judge",
      aliases=["GLWB", "lifetime withdrawal benefit", "guaranteed lifetime income rider",
               "GLIB", "lifetime income benefit rider"],
      not_=["gmwb", "gmib", "gmab", "gmdb", "other_benefit"],
      na_means="No GLWB available"),

    P("gmwb", "Guaranteed Minimum Withdrawal Benefit (GMWB)", 31, "benefits", "text",
      "Rider guaranteeing minimum withdrawals over time (GMWB), with charge and key terms if stated.",
      "judge",
      aliases=["GMWB", "minimum withdrawal benefit", "guaranteed withdrawal benefit",
               "guaranteed minimum withdrawal"],
      not_=["glwb", "gmib", "gmab", "gmdb", "other_benefit"],
      na_means="No GMWB available"),

    P("gmab", "Guaranteed Minimum Accumulation Benefit (GMAB)", 32, "benefits", "text",
      "Rider guaranteeing a minimum account value after a set period (GMAB).",
      "judge",
      aliases=["GMAB", "minimum accumulation benefit", "guaranteed accumulation benefit"],
      not_=["glwb", "gmwb", "gmib", "gmdb", "other_benefit"],
      na_means="No GMAB available"),

    P("gmdb", "Guaranteed Minimum Death Benefit (GMDB)", 33, "benefits", "text",
      "Rider guaranteeing a minimum death benefit regardless of account value (GMDB).",
      "judge",
      aliases=["GMDB", "minimum death benefit", "enhanced death benefit",
               "guaranteed death benefit rider"],
      not_=["death_benefit", "glwb", "gmwb", "gmab", "gmib", "other_benefit"],
      na_means="No GMDB available"),

    P("gmib", "Guaranteed Minimum Income Benefit (GMIB)", 34, "benefits", "text",
      "Rider guaranteeing a minimum annuitization income (GMIB).",
      "judge",
      aliases=["GMIB", "minimum income benefit", "guaranteed income benefit",
               "guaranteed annuitization benefit"],
      not_=["glwb", "gmwb", "gmab", "gmdb", "other_benefit"],
      na_means="No GMIB available"),

    P("other_benefit", "Other", 35, "benefits", "text",
      "Any guaranteed benefit or rider that is NOT GMAB, GMDB, GMIB, GLWB, GMWB, "
      "base death benefit or penalty-free withdrawals.",
      "judge",
      aliases=["other benefits", "other riders", "additional riders", "optional riders",
               "other guaranteed benefits"],
      not_=["glwb", "gmwb", "gmab", "gmdb", "gmib", "death_benefit",
            "penalty_free_withdrawals", "surrender_charge_waivers"],
      na_means="Document states no other benefits or riders",
      notes="Bare label 'Other' in the benefits block. Never confuse with other_charge "
            "or other_crediting_strategy_info."),

    # ----------------------------- availability ----------------------------- #
    P("available_plan_types", "Available Plan Types", 26, "availability", "list_text",
      "Tax-qualification plan types the product can be issued under "
      "(IRA, NQ, Roth IRA, SEP IRA, Inherited NQ, Inherited IRA, ...).",
      "set",
      aliases=["plan types", "eligible plans", "qualified and non-qualified", "tax status",
               "market types", "contract types available"],
      format_hint="list of canonical plan names, e.g. ['IRA','NQ','Roth IRA','SEP IRA']"),

    P("issue_ages", "Issue Ages", 27, "availability", "age_bands",
      "Minimum and maximum issue age by plan category (Qualified/Non-Qualified, NQ Stretch).",
      "bands",
      aliases=["issue age", "age limits", "eligible ages", "entry age", "maximum issue age",
               "age at issue"],
      format_hint="one band per plan category, e.g. {category:'Q/NQ', min_age:0, max_age:85}"),

    P("min_initial_premium", "Minimum Initial Premiums", 28, "availability", "currency_by_category",
      "Minimum first premium required, per plan category (e.g. Q/NQ).",
      "by_key",
      aliases=["minimum initial premium", "minimum premium", "initial premium minimum",
               "minimum single premium", "minimum purchase payment"],
      not_=["min_subsequent_premium"],
      format_hint="[{category: str, amount: float}]"),

    P("min_subsequent_premium", "Minimum Subsequent Premium", 29, "availability", "currency_by_category",
      "Minimum amount for additional premiums after the initial premium.",
      "by_key",
      aliases=["minimum additional premium", "subsequent premium", "additional premium minimum",
               "minimum additional payment"],
      not_=["min_initial_premium"],
      na_means="No subsequent premiums allowed (single premium product)",
      format_hint="[{category: str, amount: float}]"),

    P("state_approvals", "State Approvals", 36, "availability", "state_set",
      "US states (and DC) where the product is NOT approved, or where it is approved if only "
      "that list is given.",
      "set",
      aliases=["state availability", "states approved", "states not approved",
               "state variations", "approved states", "product availability by state",
               "states where available"],
      format_hint="{mode: 'approved'|'not_approved', states: ['CA','NY']}",
      notes="Record which mode the document uses. The normalizer converts both documents to "
            "'not_approved' over the 50 states + DC before comparison."),

    # ----------------------------- compensation ----------------------------- #
    P("street_level_compensation", "Street Level Compensation", 37, "compensation", "age_bands",
      "Commission paid to the selling agent, by year and issue-age band.",
      "bands",
      aliases=["commission", "agent compensation", "producer compensation", "commission schedule",
               "street commission", "first year commission", "advisor compensation"],
      format_hint="[{year: 'YEAR ONE', min_age: int, max_age: int|null, pct: float}]",
      notes="Open-ended bands (e.g. '81+') use max_age null."),

    # ---------------------------- product_info (tail) ----------------------- #
    P("data_current_as_of", "Data thought to be current as of:", 38, "product_info", "date",
      "Date the information in the specification was last confirmed as current.",
      "exact",
      aliases=["effective as of", "as of date", "data current as of", "last updated",
               "information current as of", "revision date", "valid as of"],
      format_hint="ISO date yyyy-mm-dd",
      notes="Document-level 'as of' date, not product launch date."),
]


# --------------------------------------------------------------------------- #
# Lookup helpers
# --------------------------------------------------------------------------- #
PROPERTIES.sort(key=lambda p: p.order)

BY_KEY: dict[str, Property] = {p.key: p for p in PROPERTIES}


def by_group(group: str) -> list[Property]:
    """Properties of one extraction group, in layout order."""
    return [p for p in PROPERTIES if p.group == group]


def siblings(prop: Property) -> list[Property]:
    """Other properties in the same group (context for 'Other' fields)."""
    return [p for p in by_group(prop.group) if p.key != prop.key]


def as_dicts() -> list[dict]:
    return [p.to_dict() for p in PROPERTIES]


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #
def validate() -> list[str]:
    errors: list[str] = []

    keys = [p.key for p in PROPERTIES]
    if len(keys) != len(set(keys)):
        errors.append("duplicate keys")

    labels = [p.label for p in PROPERTIES]
    if len(labels) != len(set(labels)):
        errors.append("duplicate labels")

    orders = [p.order for p in PROPERTIES]
    if orders != list(range(1, len(PROPERTIES) + 1)):
        errors.append(f"orders must be contiguous 1..{len(PROPERTIES)}, got {orders}")

    for p in PROPERTIES:
        if p.group not in GROUPS:
            errors.append(f"{p.key}: unknown group {p.group}")
        if p.type not in TYPES:
            errors.append(f"{p.key}: unknown type {p.type}")
        if p.compare not in COMPARE:
            errors.append(f"{p.key}: unknown compare {p.compare}")
        for ref in p.not_:
            if ref not in BY_KEY:
                errors.append(f"{p.key}: 'not' references unknown key {ref}")
            if ref == p.key:
                errors.append(f"{p.key}: 'not' references itself")
        if not p.description.strip():
            errors.append(f"{p.key}: empty description")

    for g in GROUPS:
        if not by_group(g):
            errors.append(f"group {g} has no properties")

    return errors


if __name__ == "__main__":
    errs = validate()
    if errs:
        print("INVALID:")
        for e in errs:
            print(" -", e)
        raise SystemExit(1)

    print(f"Schema v{VERSION} OK: {len(PROPERTIES)} properties\n")
    for g in GROUPS:
        props = by_group(g)
        print(f"{g} ({len(props)}): " + ", ".join(p.key for p in props))
