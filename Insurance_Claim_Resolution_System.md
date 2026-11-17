# The Intelligent Insurance Claim Resolution & Dispute Prevention System

> Project reference document (Microsoft Hackathon – selected idea). Use this as the single source of truth across all implementation phases.

---

## Table of Contents

1. [Project Summary](#1-project-summary)
2. [Why This Is a Real Insurance Problem](#2-why-this-is-a-real-insurance-problem)
3. [What We Would Build](#3-what-we-would-build)
4. [Multi-Agent System Design](#4-multi-agent-system-design)
5. [Differentiator: Counterfactual Claim Reasoning](#5-differentiator-counterfactual-claim-reasoning)
6. [How This Differs from Ordinary RAG](#6-how-this-differs-from-ordinary-rag)
7. [Technical Architecture](#7-technical-architecture)
8. [Implementation Roadmap (Phases 1–6)](#8-implementation-roadmap)
9. [Data Requirements](#9-data-requirements)
10. [Evaluation Framework](#10-evaluation-framework)
11. [Responsible Agentic AI](#11-responsible-agentic-ai)
12. [Project Rationale & Core Recommendation](#12-project-rationale--core-recommendation)
13. [Quick-Reference Checklist](#13-quick-reference-checklist)

---

## 1. Project Summary

**Focus:** Move away from fraud detection and address a different, equally difficult problem: **insurance claims that get delayed, incorrectly assessed, disputed, or escalated because the information needed to make a coverage decision is scattered across policies, endorsements, claim documents, regulations, and internal systems.**

**Idea:** An AI-powered claims resolution platform that:

- understands the complete context of a claim,
- identifies what is missing,
- coordinates the work needed to resolve it, and
- helps a human adjuster reach a defensible settlement decision.

This is more than a document chatbot or an agent that summarizes claim PDFs. It is a system that **reasons across multiple sources of evidence and executes controlled workflows.**

### Strongest recommendation

> **Build it around preventing avoidable claim delays and disputes, rather than attempting to replace the claims adjuster.**

---

## 2. Why This Is a Real Insurance Problem

### The scenario

An insurer receives a property damage claim. The customer submits:

- An insurance policy containing multiple coverage clauses
- Several endorsements that modify the original policy
- An incident report
- Photographs of the damage
- Contractor estimates and invoices
- An inspection or surveyor report
- Previous communications with the insurer

### Questions the claims adjuster must answer

1. Was the policy active on the date of the incident?
2. Does the policy cover this particular type of loss?
3. Does an endorsement modify the original coverage?
4. Is an exclusion applicable?
5. Is the submitted evidence sufficient to establish the cause and extent of loss?
6. Are the estimates reasonable and consistent with the actual damage?
7. What deductible, sublimit, depreciation, or other adjustment applies?
8. What additional investigation or documentation is needed before settlement?

These questions **depend on one another**.

### Running example (used throughout)

A property has water damage. The customer says a pipe suddenly burst. However, an inspection report suggests water may have been leaking for several weeks. The policy covers **sudden and accidental** water damage but excludes certain forms of **gradual leakage**.

- A conventional document extraction system can extract both statements.
- A basic RAG chatbot can retrieve the relevant policy clauses.
- Neither necessarily understands the real problem:

> **There is conflicting evidence about the cause of loss, and the insurer cannot responsibly reach a coverage conclusion without resolving that uncertainty.**

This is where a coordinated GenAI + Agentic AI system becomes interesting.

### Business context

- A May 2026 Indian insurance customer study reported that nearly **40% of surveyed claimants experienced delays**, and more than **50% of health insurance claimants did not receive their full claimed amount**.
- A separate 2026 industry report highlighted the continuing cost of manual claims operations.

*(Sources originally cited: Telangana Today and related industry reports. Re-verify figures before using them in presentations.)*

---

## 3. What We Would Build

An **Insurance Claim Resolution Control Tower**.

Its primary responsibility is **not** to approve or reject claims automatically. Its responsibility is to take an incomplete, complicated claim and move it toward a well-supported resolution by:

- Understanding the applicable insurance contract
- Connecting facts from different documents and systems
- Identifying missing information and conflicting evidence
- Determining what needs to happen next
- Coordinating the necessary actions
- Preparing a traceable recommendation for the claims adjuster

**Key concept:** The system should understand not only *what information exists*, but also *what information is still needed to make a reliable decision*.

---

## 4. Multi-Agent System Design

**Pattern:** Supervisor-and-specialist architecture, with **LangGraph** managing the workflow.

**Design rule:** Every agent has a specific responsibility, defined inputs, structured outputs, and permitted tools. Agents must **not** freely communicate with each other or independently execute arbitrary actions.

### 4.1 Architecture flow

```
Entry point
  New claim / Existing claim update
  (FNOL, policy documents, reports, images, invoices, communications)
        │
        ▼
Supervisor / Claim Orchestrator
  Maintains claim state, selects agents, controls transitions and approvals
        │
        ├── 1. Intake Agent               – Claim classification, FNOL normalization and triage
        ├── 2. Policy Agent               – Contract, endorsement and clause interpretation
        ├── 3. Evidence Agent             – Extracts and connects facts across documents
        ├── 4. Gap Analysis Agent         – Finds missing evidence and contradictory statements
        ├── 5. Coverage Reasoning Agent   – Maps applicable coverage conditions and exclusions
        ├── 6. Settlement Agent           – Calculations, limits, deductibles and adjustments
        ├── 7. Action Planning Agent      – Determines and initiates the next required steps
        └── 8. Quality & Audit Agent      – Checks evidence, reasoning, consistency and permissions
        │
        ▼
Human approval gate
  Claims Adjuster / Senior Reviewer
  (reviews unresolved issues, evidence and recommendations)
        │
        ▼
Controlled claim resolution
  Approved requests, settlement recommendation, communication and case updates
```

*The supervisor can revisit individual agents whenever new evidence arrives.*

### 4.2 Agent: Policy understanding & contract interpretation

More sophisticated than normal RAG. Insurance policies contain:

- Base policy conditions
- Coverage clauses
- Exclusions
- Definitions
- Endorsements
- Special conditions
- Limits and sublimits
- Deductibles

The agent must understand **how these documents modify one another**.

*Example:* The base policy covers accidental water damage, but an endorsement introduces a specific limitation for certain types of water leakage. A standard vector search might retrieve the original coverage clause without retrieving the modifying endorsement.

**Policy decomposition pipeline:**

1. Extract policy sections and clauses.
2. Identify relationships between coverage, exclusion, condition and endorsement.
3. Extract effective dates and policy versions.
4. Establish the applicable document-precedence rules for that particular policy.
5. Build a structured, versioned representation of the contract.
6. Retrieve relevant clauses with their original page numbers and text spans.

**Policy knowledge graph (conceptual):**

| Node | Question it answers |
|---|---|
| Insurance Policy | Root entity |
| Coverage Clauses | What is covered? |
| Exclusions | What is excluded? |
| Endorsements | What is modified? |
| Conditions | What must be satisfied? |
| Applicable Contract Snapshot | Version applicable on the date of loss |

**Result:** A policy representation other agents can consume instead of repeatedly interpreting entire PDFs.

### 4.3 Agent: Evidence intelligence

Understands the claim from all submitted documents.

| Document | Information extracted |
|---|---|
| FNOL | Customer reports pipe burst |
| Plumber report | Possible corrosion near pipe joint |
| Surveyor report | Moisture found in multiple areas |
| Photographs | Damage to walls and flooring |
| Contractor estimate | Repair cost of ₹4.5 lakh |
| Invoice | Plumbing repair cost of ₹35,000 |

The agent doesn't just summarize. It creates **structured facts with evidence provenance**:

```json
{
  "fact_id": "FACT-102",
  "claim_id": "CLM-001",
  "proposition": "Water damage originated from a pipe joint",
  "source_document": "plumber_report.pdf",
  "page": 3,
  "evidence_text": "Corrosion observed near the joint",
  "evidence_type": "supporting",
  "confidence": 0.91
}
```

> **Important:** The confidence value represents **extraction/interpretation confidence**, *not* the probability that the claim is covered. The agent must preserve that distinction.

### 4.4 Agent: Contradiction and missing-evidence detection (gap analysis)

Arguably the **most important component**. It compares evidence against the claim's unresolved questions.

| Question | Evidence | Status |
|---|---|---|
| Was there a sudden pipe failure? | Customer says yes | Unverified |
| Was there a gradual leak? | Corrosion noted by plumber | Possible |
| When did the damage begin? | No reliable date | Missing |
| What is the extent of damage? | Surveyor report and photos | Partially established |
| Is the proposed repair cost justified? | Contractor estimate available | Requires validation |

The agent must distinguish three different problems:

1. **Contradictory evidence**
2. **Missing evidence**
3. **Evidence that exists but does not adequately establish a particular fact**

**Most valuable capability:** Determine **the minimum additional evidence required to resolve the outstanding coverage question.**

Instead of a generic "upload more documents" request, it might recommend:

> "Request a supplementary report from the plumber specifying the suspected failure mechanism, whether corrosion predates the incident, and whether the observed damage is consistent with sudden discharge or prolonged leakage."

### 4.5 Agent: Coverage reasoning

Connects three things:

1. Applicable policy clauses
2. Established facts from submitted evidence
3. Outstanding facts that require investigation

Output is an **issue matrix**, not an unsupported binary coverage decision.

| Coverage issue | Current assessment |
|---|---|
| Policy active on incident date | Established |
| Applicable water damage coverage | Identified |
| Sudden and accidental loss condition | Unresolved |
| Gradual leakage exclusion | Potentially relevant |
| Supporting inspection evidence | Incomplete |
| Final coverage conclusion | Requires further investigation |

- Every assessment must be supported by specific policy wording and relevant evidence.
- The agent must **recognize ambiguity and abstain** rather than manufacture certainty.

### 4.6 Agent: Settlement and financial calculations

**Deliberately avoid using LLMs for arithmetic.** The LLM extracts and classifies relevant values; a **deterministic calculation engine** performs the calculations.

```
Proposed Settlement = min(Eligible Loss, Applicable Limit)
                      − Deductible
                      − Other Valid Adjustments
```

*(Exact formula depends on the product and policy terms.)*

Must account for:

- Deductibles
- Coverage limits
- Sublimits
- Depreciation
- Co-payments
- Betterment
- Salvage
- Applicable taxes and other adjustments

Each calculation must include an explanation of its inputs and the applicable policy provision.

### 4.7 Agent: Action planning & orchestration

Where the system becomes genuinely agentic. When the evidence and coverage agents identify unresolved questions, the orchestrator creates an action plan:

| Action | Responsible party | Execution |
|---|---|---|
| Obtain supplementary plumber report | Customer / plumber | Draft request |
| Schedule site inspection | Surveyor team | Create inspection task |
| Validate contractor estimate | Claims team | Assign estimate review |
| Update claim status | Claims system | Controlled API call |
| Notify customer | Customer service | Draft communication |

The orchestrator can use APIs to create tasks, check document receipt, assign reviewers, and update claim statuses.

**Incremental reasoning (strong architectural differentiator):** When new evidence arrives, the system should **not** restart the entire process. It identifies which unresolved questions the new document addresses and re-executes only the affected reasoning steps.

*Example:* A new plumber report triggers evidence analysis, contradiction detection and coverage reassessment, but does **not** require re-extracting an unchanged policy document.

---

## 5. Differentiator: Counterfactual Claim Reasoning

**Capability name: "What Would Resolve This Claim?"**

Most GenAI systems answer questions using available information. This system also reasons about **how its assessment would change when new evidence becomes available.**

**Current situation:** Coverage unresolved. The available evidence does not conclusively establish how and when the water damage occurred.

| Scenario | Outcome | What happens next |
|---|---|---|
| **A — New evidence supports sudden failure** | Potentially supports coverage | Plumber confirms abrupt pipe joint failure and inspection is consistent with the reported incident. Reassess the sudden and accidental damage provision and applicable conditions. |
| **B — New evidence supports prolonged leakage** | Potential exclusion concern | Inspection establishes prolonged leakage over several weeks. Reassess the applicable exclusion, its wording and any relevant exceptions. |
| **C — New evidence remains inconclusive** | Further investigation needed | Schedule a specialist inspection or seek supplementary technical evidence. |

This is **not** predicting approval or rejection. It maps the unresolved questions, the evidence that could address them, and the implications of different factual findings. It is especially valuable to senior claims adjusters because it reduces investigation uncertainty.

---

## 6. How This Differs from Ordinary RAG

Building eight agents doesn't by itself make an advanced Agentic AI solution.

| Capability | Basic RAG chatbot | Proposed system |
|---|---|---|
| Read insurance policies | Yes | Yes |
| Retrieve coverage clauses | Yes | Yes, with contract relationships |
| Read multiple claim documents | Possible | Yes, with evidence provenance |
| Identify contradictions | Limited | Dedicated reasoning workflow |
| Determine missing evidence | Basic checklists | Contextual gap analysis |
| Plan the next investigation | No | Yes |
| Create tasks through APIs | Usually no | Yes |
| Reassess after new documents arrive | User-driven | Event-driven |
| Maintain claim state | Limited | Persistent, structured state |
| Support audit and review | Citations | Full decision and action trace |

> **RAG retrieves information, whereas this system manages a changing claim-resolution process.**

---

## 7. Technical Architecture

Recommended stack (based on experience with LangGraph, FastAPI, Azure AI and structured LLM workflows):

| Layer | Recommended technology | Purpose |
|---|---|---|
| Document ingestion | Azure Blob Storage | Store claim documents |
| Document intelligence | Azure AI Document Intelligence | Extract text, tables and fields |
| Multimodal understanding | Azure OpenAI vision-capable model | Interpret photographs and visual reports |
| Knowledge retrieval | Azure AI Search | Hybrid policy and document retrieval |
| Agent orchestration | LangGraph | Stateful multi-agent workflows |
| Backend | FastAPI | Expose claim-processing APIs |
| Structured database | PostgreSQL / Azure SQL | Claims, facts, calculations and tasks |
| Knowledge graph | Neo4j (optional) | Connect policies, clauses, facts and evidence |
| Event processing | Azure Service Bus | Trigger workflows when new evidence arrives |
| Monitoring | Application Insights | Trace execution, errors and latency |

**Graph database guidance:** Don't introduce a graph database simply because this is an Agentic AI project. Start with relational storage and structured relationships. Add Neo4j when multi-hop evidence and policy relationships justify it.

### The most important data structure: `ClaimState`

Build a **persistent `ClaimState`** rather than passing large conversational histories between agents.

```python
class ClaimState(BaseModel):
    claim_id: str
    policy_snapshot: dict
    incident_facts: list[dict]
    evidence_items: list[dict]
    coverage_issues: list[dict]
    missing_evidence: list[dict]
    contradictions: list[dict]
    settlement_calculations: dict
    proposed_actions: list[dict]
    human_approval_required: bool
    resolution_status: str
```

Rules:

- Each agent updates **only the state fields it owns**.
- Every extracted fact retains its **source document, page, exact evidence text, extraction confidence and verification status**.
- **Version the claim state** so an adjuster can see how the system's assessment changed after additional documents.

---

## 8. Implementation Roadmap

> Don't attempt to build all eight agents immediately. Follow this progression.

### Phase 1 — Insurance document intelligence
Build an ingestion pipeline for policies, endorsements, FNOL forms, surveyor reports, estimates and invoices.
**Deliverable:** Normalized documents and structured facts with source references.

### Phase 2 — Policy intelligence
Build policy decomposition, clause relationships, endorsement handling and date-specific contract retrieval.
**Deliverable:** A structured policy knowledge base.

### Phase 3 — Evidence reasoning
Implement evidence comparison, contradiction detection and missing-document identification.
**Deliverable:** An evidence sufficiency report for each claim.

### Phase 4 — Coverage reasoning
Connect the contract representation with claim facts. Generate coverage issue matrices and conditional assessments.
**Deliverable:** An explainable claim assessment, with unresolved questions clearly identified.

### Phase 5 — Agentic orchestration
Introduce the supervisor, action planning, task creation, customer communication drafts and event-driven reassessment.
**Deliverable:** An end-to-end claim-resolution workflow.

### Phase 6 — Settlement and audit
Integrate deterministic calculations, human approval, decision traceability and monitoring.
**Deliverable:** A complete claims resolution support platform.

---

## 9. Data Requirements

Start with **one insurance product**, preferably **property insurance covering water damage**.

Build a synthetic or anonymized dataset:

| Data category | Example |
|---|---|
| Policies | Base policy, coverage terms, exclusions |
| Endorsements | Additional coverage, modified conditions |
| Claims | FNOL, claim details, incident chronology |
| Technical evidence | Plumber reports, inspection reports |
| Visual evidence | Property damage photographs |
| Financial evidence | Repair estimates, invoices |
| Communications | Customer emails, requests for information |
| Decisions | Historical adjuster assessments and settlement explanations |

**Test scenarios:** Create **30–50 carefully designed scenarios** initially, rather than thousands of random claims.

**Include difficult cases:**

- Conflicting reports
- Missing endorsements
- Expired coverage
- Multiple causes of loss
- Ambiguous exclusions
- Incomplete invoices
- New evidence that changes an earlier assessment

---

## 10. Evaluation Framework

### Technical evaluation

| Metric | What it evaluates |
|---|---|
| Policy clause retrieval accuracy | Did we retrieve the correct applicable wording? |
| Evidence extraction accuracy | Did we extract the correct facts? |
| Contradiction detection precision/recall | Did we identify conflicting evidence? |
| Missing-evidence recall | Did we identify important outstanding information? |
| Citation correctness | Can every important assertion be traced to its source? |
| Calculation accuracy | Does the deterministic engine match expected results? |
| Appropriate abstention rate | Does the system recognize when it cannot conclude? |
| Action recommendation quality | Are recommended next steps relevant and sufficient? |

### Business evaluation

Real success measures:

- Reduction in average claim resolution time
- Reduction in repeated requests for the same documentation
- Reduction in manual investigation effort
- Reduction in avoidable claim disputes and escalations
- Improvement in customer communication turnaround
- Reduction in reopened claims caused by incomplete assessments

> **Establish a human-reviewed baseline first. Don't invent an expected percentage improvement before measuring the baseline.**

---

## 11. Responsible Agentic AI

The system must **not** autonomously reject a claim, issue an adverse coverage decision, or authorize a settlement. Explicit approval boundaries:

| Operation | Autonomy |
|---|---|
| Extract information from documents | Autonomous |
| Retrieve policy clauses | Autonomous |
| Identify missing evidence | Autonomous |
| Draft requests for information | Autonomous, draft-only |
| Create an investigation task | Controlled API action |
| Recommend coverage assessment | Human-reviewed |
| Recommend settlement amount | Human-reviewed |
| Deny a claim | Authorized human decision |
| Release settlement payment | Authorized human decision |

This is important for real-world insurance deployment, not just an architectural preference.

**Regulatory context (India):**

- IRDAI's December 2025 explanation of the motor claims framework emphasizes transparent, reasonable deductions supported by documentary explanations.
- In June 2026, IRDAI constituted a dedicated AI governance working group for the insurance sector.

*(Sources originally cited: Press Information Bureau. Re-verify before citing.)*

**Audit trail must capture:**

- Original evidence
- Relevant policy wording
- Agent outputs
- Calculation inputs
- Human overrides
- Final decision

---

## 12. Project Rationale & Core Recommendation

### Why not other insurance AI ideas?

Several use cases look impressive in demos but aren't particularly challenging:

- Insurance chatbot
- Policy summarization
- Claim document extraction
- Simple claim classification
- Basic RAG over insurance documents

### Three technological foundations

1. **Contract intelligence** – Understand complex policy structures, endorsements, exclusions and applicable conditions.
2. **Evidence-based reasoning** – Connect facts across multiple documents, discover contradictions and reason about what information is missing.
3. **Autonomous workflow orchestration** – Decide the next best investigation step, coordinate tasks and reassess the claim when new evidence arrives.

### The core challenge

> The most interesting research/engineering challenge isn't making an LLM understand an insurance policy. It's making an AI system understand **what it doesn't know, why that information matters, and what action would resolve the uncertainty.**

### Skills demonstrated

Multimodal AI, hybrid RAG, knowledge graphs, structured extraction, multi-agent state machines, deterministic financial calculations, tool calling, event-driven workflows, evaluation frameworks and human-in-the-loop governance.

### Final recommendation

> **Make the *evidence sufficiency and next-best-investigation engine* the heart of the project.** Policy RAG, document extraction and settlement calculations should support that central capability, not become separate disconnected demos. This is where the most engineering effort should go.

---

## 13. Quick-Reference Checklist

**Guiding principles**

- [ ] Prevent delays/disputes; do not replace the adjuster
- [ ] Evidence sufficiency + next-best-investigation is the core
- [ ] Persistent, versioned `ClaimState` (no long chat histories between agents)
- [ ] Each agent owns specific state fields, has structured outputs and permitted tools
- [ ] Every fact carries provenance (document, page, text, confidence, verification status)
- [ ] Extraction confidence ≠ probability of coverage
- [ ] LLMs never do arithmetic; deterministic engine does
- [ ] Abstain when ambiguous
- [ ] Incremental, event-driven reassessment (re-run only affected steps)
- [ ] Human approval for coverage, denial, settlement and payment
- [ ] Start with relational storage; add Neo4j only when justified
- [ ] Measure a human baseline before claiming improvements

**Phase tracker**

- [ ] Phase 1 – Document intelligence
- [ ] Phase 2 – Policy intelligence
- [ ] Phase 3 – Evidence reasoning
- [ ] Phase 4 – Coverage reasoning
- [ ] Phase 5 – Agentic orchestration
- [ ] Phase 6 – Settlement and audit
