CREATE TABLE IF NOT EXISTS radar_schema_migrations (
    version TEXT PRIMARY KEY,
    checksum TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE radar_terms (
    id UUID PRIMARY KEY,
    canonical_key TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('name', 'generic', 'unknown')),
    language TEXT NOT NULL,
    first_seen_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE radar_evidence (
    id UUID PRIMARY KEY,
    term_id UUID NOT NULL REFERENCES radar_terms(id) ON DELETE RESTRICT,
    source_instance TEXT NOT NULL,
    external_id TEXT NOT NULL,
    entity_key TEXT NOT NULL,
    slot TEXT NOT NULL,
    url TEXT NOT NULL,
    excerpt TEXT NOT NULL CHECK (char_length(excerpt) <= 500),
    observed_at TIMESTAMPTZ NOT NULL,
    data_window JSONB NOT NULL,
    metrics JSONB NOT NULL,
    content_hash TEXT NOT NULL,
    is_discovery BOOLEAN NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source_instance, external_id, slot, term_id)
);

CREATE TABLE radar_relations (
    id UUID PRIMARY KEY,
    name_id UUID NOT NULL REFERENCES radar_terms(id) ON DELETE RESTRICT,
    generic_id UUID NOT NULL REFERENCES radar_terms(id) ON DELETE RESTRICT,
    evidence_id UUID NOT NULL REFERENCES radar_evidence(id) ON DELETE RESTRICT,
    phrase TEXT NOT NULL,
    language TEXT NOT NULL,
    quote TEXT NOT NULL CHECK (char_length(quote) <= 500),
    rule_version TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (name_id, generic_id, evidence_id, rule_version)
);

CREATE TABLE radar_source_state (
    source_instance TEXT PRIMARY KEY,
    version INTEGER NOT NULL CHECK (version >= 0),
    payload JSONB NOT NULL,
    last_success_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE radar_jobs (
    job_key TEXT PRIMARY KEY,
    task TEXT NOT NULL,
    payload JSONB NOT NULL,
    scheduled_for TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'leased', 'complete', 'failed')),
    lease_token UUID,
    lease_expires_at TIMESTAMPTZ,
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    result JSONB,
    error JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK ((status = 'leased') = (lease_token IS NOT NULL AND lease_expires_at IS NOT NULL))
);

CREATE TABLE radar_runs (
    id UUID PRIMARY KEY,
    job_key TEXT NOT NULL REFERENCES radar_jobs(job_key) ON DELETE RESTRICT,
    lease_token UUID NOT NULL,
    source_instance TEXT,
    status TEXT NOT NULL CHECK (status IN ('ok', 'baseline', 'off', 'incomplete', 'failed', 'skipped')),
    result JSONB,
    error JSONB,
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ NOT NULL,
    CHECK (finished_at >= started_at)
);

CREATE TABLE radar_checks (
    id UUID PRIMARY KEY,
    term_id UUID NOT NULL REFERENCES radar_terms(id) ON DELETE RESTRICT,
    checkpoint_days INTEGER NOT NULL CHECK (checkpoint_days IN (3, 14)),
    status TEXT NOT NULL CHECK (status IN ('sustained', 'not_sustained', 'insufficient_data')),
    evidence JSONB NOT NULL,
    due_at TIMESTAMPTZ NOT NULL,
    checked_at TIMESTAMPTZ NOT NULL,
    UNIQUE (term_id, checkpoint_days)
);

CREATE TABLE radar_reports (
    id UUID PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('daily', 'weekly')),
    period_start TIMESTAMPTZ NOT NULL,
    period_end TIMESTAMPTZ NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (kind, period_start),
    CHECK (period_end > period_start)
);

CREATE INDEX radar_evidence_term_observed_idx ON radar_evidence (term_id, observed_at DESC);
CREATE INDEX radar_evidence_source_observed_idx ON radar_evidence (source_instance, observed_at DESC);
CREATE INDEX radar_jobs_due_idx ON radar_jobs (status, scheduled_for, lease_expires_at);
CREATE INDEX radar_runs_source_finished_idx ON radar_runs (source_instance, finished_at DESC);
CREATE INDEX radar_checks_due_idx ON radar_checks (due_at, status);

