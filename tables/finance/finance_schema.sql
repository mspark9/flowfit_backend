-- ============================================================
-- Enterprise AI Hub — 재무팀 테이블 DDL (PostgreSQL)
-- 실행: psql -U <user> -d <db> -f tables/finance/finance_schema.sql
-- ============================================================

-- ────────────────────────────────────────────────────────────
-- 1. 전표 / 거래 내역 (경리/회계 · OCR 분류 결과)
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS finance_transactions (
    id              SERIAL          PRIMARY KEY,
    receipt_date    DATE            NOT NULL,                   -- 영수증 날짜
    item            VARCHAR(255)    NOT NULL,                   -- 항목명
    amount          INTEGER         NOT NULL,                   -- 공급가액 (원)
    tax_amount      INTEGER         NOT NULL DEFAULT 0,         -- 부가세 (원)
    total_amount    INTEGER         GENERATED ALWAYS AS (amount + tax_amount) STORED,
    account_code    VARCHAR(100)    NOT NULL,                   -- 계정과목
    department      VARCHAR(100),                              -- 부서
    vendor          VARCHAR(255),                              -- 거래처
    memo            TEXT,                                      -- 적요
    ai_confidence   NUMERIC(5, 2),                             -- AI 신뢰도 (0.00~100.00)
    raw_json        JSONB,                                     -- OpenAI 원본 응답 보관
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_finance_transactions_receipt_date  ON finance_transactions (receipt_date);
CREATE INDEX IF NOT EXISTS idx_finance_transactions_account_code  ON finance_transactions (account_code);
CREATE INDEX IF NOT EXISTS idx_finance_transactions_department    ON finance_transactions (department);

-- ────────────────────────────────────────────────────────────
-- 2. 예산 (재무/자금 · 부서별 연간 예산 관리)
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS finance_budgets (
    id              SERIAL          PRIMARY KEY,
    fiscal_year     SMALLINT        NOT NULL,                  -- 회계연도
    department      VARCHAR(100)    NOT NULL,                  -- 부서
    account_code    VARCHAR(100)    NOT NULL,                  -- 계정과목
    budget_amount   INTEGER         NOT NULL,                  -- 배정 예산 (원)
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    UNIQUE (fiscal_year, department, account_code)
);

CREATE INDEX IF NOT EXISTS idx_finance_budgets_fiscal_year   ON finance_budgets (fiscal_year);
CREATE INDEX IF NOT EXISTS idx_finance_budgets_department    ON finance_budgets (department);

-- ────────────────────────────────────────────────────────────
-- 3. 감사 로그 (내부감사 · FDS 탐지 결과)
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS finance_audit_logs (
    id              SERIAL          PRIMARY KEY,
    transaction_id  INTEGER         REFERENCES finance_transactions (id) ON DELETE SET NULL,
    risk_level      VARCHAR(10)     NOT NULL CHECK (risk_level IN ('safe', 'warning', 'danger')),
    violated_rule   VARCHAR(255),                              -- 위반 규정 조항
    ai_reason       TEXT            NOT NULL,                  -- AI 판단 사유
    is_confirmed    BOOLEAN         NOT NULL DEFAULT FALSE,    -- 담당자 확인 여부
    confirmed_by    VARCHAR(100),                              -- 확인자
    confirmed_at    TIMESTAMPTZ,
    raw_json        JSONB,                                     -- OpenAI 원본 응답 보관
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_finance_audit_logs_risk_level      ON finance_audit_logs (risk_level);
CREATE INDEX IF NOT EXISTS idx_finance_audit_logs_transaction_id  ON finance_audit_logs (transaction_id);
CREATE INDEX IF NOT EXISTS idx_finance_audit_logs_is_confirmed    ON finance_audit_logs (is_confirmed);

-- ────────────────────────────────────────────────────────────
-- updated_at 자동 갱신 트리거
-- ────────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_finance_transactions_updated_at') THEN
        CREATE TRIGGER trg_finance_transactions_updated_at
            BEFORE UPDATE ON finance_transactions
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_finance_budgets_updated_at') THEN
        CREATE TRIGGER trg_finance_budgets_updated_at
            BEFORE UPDATE ON finance_budgets
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    END IF;
END $$;
