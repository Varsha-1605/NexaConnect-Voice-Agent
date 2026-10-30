CREATE TABLE IF NOT EXISTS enrollments (
    id                          BIGSERIAL PRIMARY KEY,
    enrollment_reference        TEXT NOT NULL UNIQUE,
    customer_name               TEXT NOT NULL,
    phone_number                TEXT NOT NULL,
    email                       TEXT,
    service_address             TEXT NOT NULL,
    city                        TEXT NOT NULL,
    state                       TEXT NOT NULL,
    postal_code                 TEXT NOT NULL,
    plan_name                   TEXT NOT NULL,
    monthly_plan_price          NUMERIC(10, 2) NOT NULL,
    router_rental_selected      BOOLEAN NOT NULL DEFAULT FALSE,
    preferred_installation_date DATE,
    enrollment_status           TEXT NOT NULL DEFAULT 'submitted',
    consent_given_at            TIMESTAMPTZ NOT NULL,
    idempotency_key             TEXT NOT NULL UNIQUE,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS cancellations (
    id                      BIGSERIAL PRIMARY KEY,
    cancellation_reference  TEXT NOT NULL UNIQUE,
    enrollment_id           BIGINT NOT NULL UNIQUE REFERENCES enrollments (id),
    cancellation_reason     TEXT NOT NULL,
    cancellation_status     TEXT NOT NULL DEFAULT 'submitted',
    effective_date          DATE NOT NULL,
    consent_given_at        TIMESTAMPTZ NOT NULL,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS account_changes (
    id                BIGSERIAL PRIMARY KEY,
    enrollment_id     BIGINT NOT NULL REFERENCES enrollments (id),
    field_name        TEXT NOT NULL,
    old_value         TEXT,
    new_value         TEXT NOT NULL,
    consent_given_at  TIMESTAMPTZ NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS bills (
    id              BIGSERIAL PRIMARY KEY,
    enrollment_id   BIGINT NOT NULL UNIQUE REFERENCES enrollments (id),
    period_start    DATE NOT NULL,
    period_end      DATE NOT NULL,
    due_date        DATE NOT NULL,
    total_amount    NUMERIC(10, 2) NOT NULL,
    line_items      JSONB NOT NULL,
    payment_status  TEXT NOT NULL,
    amount_paid     NUMERIC(10, 2) NOT NULL DEFAULT 0,
    paid_on         DATE
);

CREATE TABLE IF NOT EXISTS support_tickets (
    id                BIGSERIAL PRIMARY KEY,
    ticket_reference  TEXT NOT NULL UNIQUE,
    enrollment_id     BIGINT NOT NULL REFERENCES enrollments (id),
    billing_issue     TEXT NOT NULL,
    issue_details     TEXT NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
