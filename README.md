# Sentinel: The Neuro-Symbolic Trust Layer

![Sentinel Shield](path/to/image)

**Team:** Symbolic Overlords · **Hackathon:** IBM AI Demystified

> *"In the space between thought and execution, Sentinel stands guard."*

---

## The Problem

Large language models can generate SQL from natural language—fast and fluid. But that power carries risk: a single misinterpreted prompt can produce a `DROP TABLE` or a sweeping `DELETE` that bypasses human oversight. Enterprises fear putting LLM-generated queries directly against production databases. The neural output is opaque; one mistake, and the blast radius is real.

---

## The Solution

**Decoupling reasoning from execution.** Sentinel is a **fail-closed** governance layer that sits between watsonx Orchestrate (and the LLM, e.g. IBM Granite) and your Db2 database. Every generated SQL statement is validated against a **symbolic** rule set stored in Db2 before any query runs. No rule match → **Allow**. Destructive or policy-breaking pattern → **Block** or **Intercept** with a suggested rewrite (e.g. soft-delete instead of hard delete). The "neuro" side produces the SQL; the "symbolic" side decides whether it is safe to run.

---

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  watsonx        │     │  Sentinel       │     │  Db2            │
│  Orchestrate    │────▶│  (this repo)    │────▶│  (rules + data)  │
│  (Granite LLM)  │     │  validate_intent│     │  SENTINEL_RULES │
└─────────────────┘     └─────────────────┘     └─────────────────┘
       │                          │
       │  Generated SQL            │  ALLOW / BLOCK / REWRITE
       └──────────────────────────┘
```

- **watsonx → Sentinel:** Raw SQL from the LLM is sent to Sentinel.
- **Sentinel → Db2:** Rules are read from `SENTINEL_RULES` (see [governance_schema.sql](src/governance_schema.sql)); in this repo the rule set is mocked for demo.
- **Sentinel → Caller:** Response is either *allowed* or a structured *blocking object* (rule_id, message, suggested_fix).

---

## Validation Logic

The core behavior lives in **[`src/sentinel_logic.py`](src/sentinel_logic.py)**:

- **`SentinelGuard`** — Class that performs the neuro-symbolic handshake: it takes generated SQL and a rule set (from Db2 in production, or mocked for the demo).
- **`validate_intent(generated_sql, rule_set)`** — Returns a structured result: `ALLOW`, `BLOCK_CRITICAL`, or `INTERCEPT_REWRITE`, with optional `suggested_fix` (e.g. *"UPDATE status = 'ARCHIVED'"* instead of DELETE).

The file is heavily commented to show how the symbolic layer (Db2 rules) is used to validate the neural output (LLM SQL).

---

## Team

**Symbolic Overlords** — IBM AI Demystified Hackathon submission.

---

## Test Protocol

We use a prompt/SQL matrix to prove that Sentinel behaves correctly across safe, rewrite, and block scenarios:

| File | Purpose |
|------|--------|
| **[`tests/test_prompts.csv`](tests/test_prompts.csv)** | Rows: user intent, generated SQL, expected Sentinel action (ALLOW, INTERCEPT_REWRITE, BLOCK_CRITICAL). Used to drive validation tests and demonstrate rigor. |

Example rows:

- *"Show Q3 sales"* → read-only `SELECT` → **ALLOW**
- *"Delete old records"* → `DELETE FROM ...` → **INTERCEPT_REWRITE** (suggest soft-delete)
- *"Drop users table"* → `DROP TABLE users` → **BLOCK_CRITICAL**

Run validation against this CSV to ensure every prompt/SQL pair yields the expected Sentinel action.

---

## Repo Layout

```
sentinel-core/
├── src/
│   ├── __init__.py
│   ├── sentinel_logic.py      # Core guard + validate_intent
│   ├── governance_schema.sql # Db2 SENTINEL_RULES schema & demo rules
│   └── db2_connector.py      # Placeholder Db2 connection
├── examples/
│   └── demo_payload.json     # Sample blocked event (e.g. DROP TABLE)
├── tests/
│   └── test_prompts.csv      # Safe vs. unsafe prompt matrix
├── requirements.txt          # ibm-generative-ai, ibm_db
└── README.md
```

---

## Quick Start

```bash
pip install -r requirements.txt
# Run Sentinel against test_prompts.csv or call SentinelGuard.validate_intent() with your SQL.
```

Example blocked response shape (see **[`examples/demo_payload.json`](examples/demo_payload.json)**):

- `violation_detected`: true  
- `rule_id`: `"GOV-404"`  
- `sentinel_action`: `"INTERCEPT"`  
- `message`: `"Destructive Operation Detected"`

---

*Sentinel: The Neuro-Symbolic Trust Layer for watsonx Orchestrate.*
