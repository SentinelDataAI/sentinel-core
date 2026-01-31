-- =============================================================================
-- Sentinel Governance Schema (Db2)
-- =============================================================================
-- This schema defines the SYMBOLIC layer: rules that Sentinel evaluates
-- against LLM-generated SQL. The existence of this table is the "proof" that
-- governance is rule-driven (symbolic), not ad-hoc.
-- Team: Symbolic Overlords | IBM AI Demystified Hackathon
-- =============================================================================

-- Table: SENTINEL_RULES
-- Stores governance rules. Each row defines a pattern and the action
-- (BLOCK_CRITICAL, INTERCEPT_REWRITE, or ALLOW) when the pattern is found
-- in generated SQL.
CREATE TABLE SENTINEL_RULES (
    rule_id       VARCHAR(32)   NOT NULL PRIMARY KEY,
    pattern       VARCHAR(256)  NOT NULL,
    action        VARCHAR(64)   NOT NULL,
    description   VARCHAR(512),
    active        SMALLINT      DEFAULT 1,
    created_at    TIMESTAMP     DEFAULT CURRENT_TIMESTAMP,
    updated_at    TIMESTAMP     DEFAULT CURRENT_TIMESTAMP
);

-- Index for fast lookup of active rules during validation.
CREATE INDEX idx_sentinel_rules_active ON SENTINEL_RULES(active) WHERE active = 1;

-- =============================================================================
-- Demo rules (used by sentinel_logic.py and test_prompts.csv)
-- =============================================================================

-- GOV-404: DROP TABLE -> BLOCK_CRITICAL (destructive DDL)
INSERT INTO SENTINEL_RULES (rule_id, pattern, action, description) VALUES
('GOV-404', 'DROP TABLE', 'BLOCK_CRITICAL', 'Destructive DDL — table drop forbidden');

-- GOV-101: DELETE -> INTERCEPT_REWRITE (suggest soft-delete)
INSERT INTO SENTINEL_RULES (rule_id, pattern, action, description) VALUES
('GOV-101', 'DELETE', 'INTERCEPT_REWRITE', 'Bulk delete intercepted; suggest soft-delete (e.g. UPDATE status = ARCHIVED)');

-- =============================================================================
-- Optional: audit log for every validation (production use)
-- =============================================================================
-- CREATE TABLE SENTINEL_AUDIT (
--     id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
--     generated_sql  CLOB,
--     rule_id        VARCHAR(32),
--     action         VARCHAR(64),
--     created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
-- );
