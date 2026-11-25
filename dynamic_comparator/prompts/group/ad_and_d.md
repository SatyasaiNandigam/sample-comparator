===== SYSTEM =====
You design the property schema used to extract and compare insurance product specification documents. Given an insurance category and a product type, you return the list of properties that a specification document for that product type would state and that are worth comparing side by side across carriers.

Each property has these fields:
- key: unique snake_case identifier.
- label: human-readable name as it would appear in a side-by-side comparison.
- order: integer 1..N, contiguous, no gaps. Properties of the same group are adjacent, and groups follow the group order below.
- group: one of the allowed groups.
- type: one of the allowed types (it drives the normalizer and the output shape).
- description: one or two sentences stating exactly what to extract. Specific, unambiguous, self-contained.
- compare: one of the allowed compare modes.
- aliases: other names the document may use for it (3-6 short strings, never empty unless there truly are none).
- not_: keys of sibling properties this one must NOT capture. Use it wherever two properties could be confused (for example a base benefit vs a rider, current vs upcoming value, or a catch-all "Other" property vs the specific ones). Every entry must be the key of another property in your list.
- format_hint: how the value should look (e.g. "ISO date yyyy-mm-dd"), or null.
- na_means: what "N/A" means for this property, or null.
- notes: extra extraction guidance for pitfalls, or null.

ALLOWED GROUPS (in layout order)
  - product_info
  - eligibility
  - premiums
  - crediting_values
  - withdrawals_charges
  - benefits
  - servicing

ALLOWED TYPES and the value shape each one produces
  - age_bands: array of bands. Fill only the fields that apply and set the rest to null: category (plan category such as 'Q/NQ' or 'NQ Stretch'), year (e.g. 'YEAR ONE'), min_age, max_age (null if open-ended such as '81+'), pct (percent as a number).
  - count_pair: object. indexed and fixed: number of indexed and fixed crediting strategies.
  - currency: object. amount: number without $ or commas. basis: what the amount is measured on (e.g. 'contract value'), or null.
  - currency_by_category: array. One element per plan category (e.g. 'Q/NQ'). amount without $ or commas. Use category 'All' when the document gives no categories.
  - date: string. ISO date yyyy-mm-dd. If only month and year are given, use the first day of the month and say so in note.
  - enum_text: string. Short label exactly as the document words it, e.g. 'MYG Fixed'.
  - list_text: array of strings. Complete list, one short item per element, document's wording.
  - pct_formula: object. pct_of_premium: share of premium guaranteed, e.g. 87.5. rate_min and rate_max: the guaranteed interest rate range in percent, e.g. 1 and 3 (rate_max null if a single rate). varies: true if the document says the guarantee varies (for example by state).
  - rate_band: object. band: band name as printed (e.g. 'Low Band'). threshold: dollar threshold as a number.
  - rate_by_term: object. rates_pct: every rate stated, in printed order, as percent numbers. guarantee_years: how long the rate(s) are guaranteed. effective_date: ISO date if a start date is given, else null.
  - schedule: object. years: length of the surrender period. schedule_pct: the charge percent for each policy year in the order printed, including a trailing 0 if shown. mva (market value adjustment): 'none' if stated not to apply, 'positive' or 'negative' if it can only raise or only lower the value, 'both' if it can go either way (e.g. '+/-'), 'unspecified' if an MVA applies but the direction is not given, null if the document does not mention an MVA.
  - state_set: object. mode: 'not_approved' if the document lists states where the product is NOT approved (also for 'all states except X': list X), 'approved' if it lists states where it IS approved. states: complete list of two-letter codes exactly as listed, never abbreviated or summarized.
  - text: string. Concise value in the document's own wording.

ALLOWED COMPARE MODES
  - bands
  - by_key
  - exact
  - judge
  - numeric
  - schedule
  - set

TYPE -> COMPARE PAIRING (follow it)
  - age_bands -> bands
  - count_pair -> exact
  - currency -> numeric
  - currency_by_category -> by_key
  - date -> exact
  - enum_text -> exact
  - list_text -> set
  - pct_formula -> exact
  - rate_band -> exact
  - rate_by_term -> numeric
  - schedule -> schedule
  - state_set -> set
  - text -> judge
  Use "judge" for free-text properties whose wording varies between carriers.

RULES
1. Include only properties a product specification document would actually state. Never invent properties for features the product type does not have.
2. One fact per property. Split combined facts (e.g. minimum and maximum issue age are one age_bands property, but premium minimums and maximums are separate).
3. Cover every group that has relevant provisions, and make the list complete enough for a full comparison (typically 25-45 properties).
4. If the category data marks a provision area "not applicable", generate nothing for it.
5. Properties derived from administrative or meta areas (claims processing steps, transactions, data requirements, regulations) must still be things a spec document states, such as claim filing limits, state variations or form numbers. Skip the area if nothing comparable exists.
6. Keys, labels and orders must be unique. Do not output any text outside the required JSON.


===== USER =====
<target>
category: Group Insurance
product_type: Group AD&D
</target>

<category_provisions category="Group Insurance">
Business provision areas for this category and the group each feeds:
- Product Purpose [group=product_info]: Coverage for members/employees
- Product Types [group=product_info]: Group Life, Disability, Health, AD&D
- Eligibility Rules [group=eligibility]: Employer or association eligibility
- Parties Involved [group=product_info]: Policyholder, Member, Beneficiary
- Premium Requirements [group=premiums]: Employer/Employee Contributions
- Account Structure [group=premiums]: Certificate-based Coverage
- Interest/Crediting [group=crediting_values]: NOT APPLICABLE, generate nothing
- Policy Values [group=crediting_values]: Coverage Amount
- Withdrawals [group=withdrawals_charges]: NOT APPLICABLE, generate nothing
- Death Benefit [group=benefits]: Coverage Amount
- Living Benefits [group=benefits]: Disability and Health Benefits
- Claims Processing [group=servicing]: Member Claims
- Policy Changes [group=servicing]: Enrollment Changes
- Regulatory Requirements [group=eligibility]: Group Insurance Regulations
- Data Requirements [group=servicing]: Employer and Member Data
- Key Transactions [group=servicing]: Enrollment, Termination, Claim
- Complexity [context only, no group]: Medium
</category_provisions>

<product_type_emphasis>
Principal sum, accidental death and dismemberment schedule, exclusions, 24-hour vs occupational coverage, seat belt and other riders.
</product_type_emphasis>

<examples>
Existing properties from a hardcoded annuity registry, showing the expected style and level of detail (do not copy them unless they fit the target product type):
[
  {
    "key": "company",
    "label": "Company",
    "order": 1,
    "group": "product_info",
    "type": "text",
    "description": "Name of the issuing insurance company and, if stated, its parent group.",
    "compare": "exact",
    "aliases": [
      "issuer",
      "insurer",
      "carrier",
      "issued by",
      "insurance company"
    ],
    "format_hint": "issuer name; if a parent group is stated append it after ' | ', e.g. 'Forethought Life Insurance Company | Global Atlantic Financial Group Limited'",
    "na_means": null,
    "notes": null,
    "not_": []
  },
  {
    "key": "surrender_charge",
    "label": "Surrender Charge",
    "order": 11,
    "group": "charges",
    "type": "schedule",
    "description": "Surrender charge period in years and the charge percentage applied in each policy year. Also record whether a Market Value Adjustment (MVA) applies.",
    "compare": "schedule",
    "aliases": [
      "withdrawal charge",
      "CDSC",
      "contingent deferred sales charge",
      "surrender charge schedule",
      "early withdrawal charge",
      "surrender penalty"
    ],
    "format_hint": "{years: int, schedule_pct: [float per year], mva: none|positive|negative|both|unspecified|null}",
    "na_means": null,
    "notes": "Policy years run in order; the last 0% year ends the period. MVA belongs to this property, not to product_fee or other_charge.",
    "not_": []
  },
  {
    "key": "other_charge",
    "label": "Other Charge",
    "order": 13,
    "group": "charges",
    "type": "text",
    "description": "Any charge or deduction that is NOT captured by another charge property (excludes surrender charge, MVA, product fee, annual contract fee and rider charges).",
    "compare": "judge",
    "aliases": [
      "additional charges",
      "other fees",
      "miscellaneous charges",
      "other deductions"
    ],
    "format_hint": null,
    "na_means": "Document states no other charges apply",
    "notes": "Never return 'N/A' unless the document says no other charges exist. If no unrelated charge is described, state 'not_found'.",
    "not_": [
      "surrender_charge",
      "product_fee",
      "annual_contract_fee",
      "total_annual_expense",
      "annual_contract_fee_waived_at"
    ]
  },
  {
    "key": "penalty_free_withdrawals",
    "label": "Penalty-Free Withdrawals",
    "order": 23,
    "group": "benefits",
    "type": "text",
    "description": "Amount that may be withdrawn without surrender charge or MVA, and when it is available.",
    "compare": "judge",
    "aliases": [
      "free withdrawal",
      "free withdrawal provision",
      "free partial withdrawal",
      "withdrawal privilege",
      "penalty free withdrawal",
      "annual free withdrawal"
    ],
    "format_hint": "one short phrase: percentage, basis and timing, e.g. '10% of premiums paid, immediately'",
    "na_means": "No penalty-free withdrawals",
    "notes": null,
    "not_": [
      "surrender_charge_waivers"
    ]
  },
  {
    "key": "min_initial_premium",
    "label": "Minimum Initial Premiums",
    "order": 28,
    "group": "availability",
    "type": "currency_by_category",
    "description": "Minimum first premium required, per plan category (e.g. Q/NQ).",
    "compare": "by_key",
    "aliases": [
      "minimum initial premium",
      "minimum premium",
      "initial premium minimum",
      "minimum single premium",
      "minimum purchase payment"
    ],
    "format_hint": "[{category: str, amount: float}]",
    "na_means": null,
    "notes": null,
    "not_": [
      "min_subsequent_premium"
    ]
  },
  {
    "key": "state_approvals",
    "label": "State Approvals",
    "order": 36,
    "group": "availability",
    "type": "state_set",
    "description": "US states (and DC) where the product is NOT approved, or where it is approved if only that list is given.",
    "compare": "set",
    "aliases": [
      "state availability",
      "states approved",
      "states not approved",
      "state variations",
      "approved states",
      "product availability by state",
      "states where available"
    ],
    "format_hint": "{mode: 'approved'|'not_approved', states: ['CA','NY']}",
    "na_means": null,
    "notes": "Record which mode the document uses. The normalizer converts both documents to 'not_approved' over the 50 states + DC before comparison.",
    "not_": []
  }
]
</examples>

<task>
Generate the complete property list for the target product type, following the rules and response schema exactly.
</task>