-- =============================================================================
-- Sentinel DB Schema (Db2) — Reference Definitions
-- =============================================================================
-- Safe to share: table and index definitions only. No proprietary logic.
-- Public Evaluation Build
-- =============================================================================

-- -----------------------------------------------------------------------------
-- SENTINEL_RULES — Governance rule table
-- -----------------------------------------------------------------------------
CREATE TABLE SENTINEL_RULES (
    rule_id       VARCHAR(32)   NOT NULL PRIMARY KEY,
    pattern       VARCHAR(256)  NOT NULL,
    action        VARCHAR(64)   NOT NULL,
    description   VARCHAR(512),
    active        SMALLINT      DEFAULT 1,
    created_at    TIMESTAMP     DEFAULT CURRENT_TIMESTAMP,
    updated_at    TIMESTAMP     DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_sentinel_rules_active ON SENTINEL_RULES(active) WHERE active = 1;

-- -----------------------------------------------------------------------------
-- AUDIT_LOG — Validation audit trail
-- -----------------------------------------------------------------------------
CREATE TABLE AUDIT_LOG (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_id         VARCHAR(64) NOT NULL,
    session_id       VARCHAR(64),
    timestamp        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    event_type       VARCHAR(32) NOT NULL,
    verdict          VARCHAR(16) NOT NULL,
    rule_id          VARCHAR(32),
    original_sql     CLOB,
    risk_score       DECIMAL(5, 4),
    latency_ms       DECIMAL(10, 2),
    metadata         CLOB,
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_audit_session ON AUDIT_LOG(session_id);
CREATE INDEX idx_audit_timestamp ON AUDIT_LOG(timestamp);
CREATE INDEX idx_audit_verdict ON AUDIT_LOG(verdict);

-- -----------------------------------------------------------------------------
-- Demo rule inserts (reference only)
-- -----------------------------------------------------------------------------
-- INSERT INTO SENTINEL_RULES (rule_id, pattern, action, description) VALUES
-- ('GOV-404', 'DROP TABLE', 'BLOCK_CRITICAL', 'Destructive DDL — table drop forbidden');
-- INSERT INTO SENTINEL_RULES (rule_id, pattern, action, description) VALUES
-- ('GOV-101', 'DELETE', 'INTERCEPT_REWRITE', 'Bulk delete intercepted; suggest soft-delete');
