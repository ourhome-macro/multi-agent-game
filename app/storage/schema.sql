-- PostgreSQL runtime persistence schema for the multi-agent narrative system.
-- World events are the authority. Projection tables exist only for hot reads.

CREATE TABLE IF NOT EXISTS schema_migrations (
    name text PRIMARY KEY,
    version integer NOT NULL CHECK (version > 0),
    description text NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO schema_migrations (name, version, description)
VALUES ('postgres_runtime_schema', 1, 'Initial PostgreSQL runtime schema')
ON CONFLICT (name) DO UPDATE
SET version = GREATEST(schema_migrations.version, EXCLUDED.version),
    description = EXCLUDED.description,
    applied_at = now()
WHERE schema_migrations.version IS DISTINCT FROM EXCLUDED.version
   OR schema_migrations.description IS DISTINCT FROM EXCLUDED.description;

CREATE TABLE IF NOT EXISTS app_sessions (
    id text PRIMARY KEY,
    case_id text NOT NULL,
    current_sequence bigint NOT NULL DEFAULT 0 CHECK (current_sequence >= 0),
    current_version bigint NOT NULL DEFAULT 0 CHECK (current_version >= 0),
    narrative_phase text NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS world_events (
    id text PRIMARY KEY,
    session_id text NOT NULL REFERENCES app_sessions(id) ON DELETE CASCADE,
    case_id text NOT NULL,
    sequence bigint NOT NULL CHECK (sequence > 0),
    actor_id text NOT NULL,
    type text NOT NULL,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    caused_by_event_id text NULL,
    idempotency_key text NULL,
    schema_version integer NOT NULL DEFAULT 1 CHECK (schema_version > 0),
    created_at timestamptz NOT NULL,
    persisted_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (session_id, sequence),
    UNIQUE (session_id, id),
    FOREIGN KEY (session_id, caused_by_event_id)
        REFERENCES world_events(session_id, id)
        DEFERRABLE INITIALLY DEFERRED
);

CREATE INDEX IF NOT EXISTS idx_world_events_session_sequence
    ON world_events(session_id, sequence);

CREATE INDEX IF NOT EXISTS idx_world_events_session_type
    ON world_events(session_id, type);

CREATE INDEX IF NOT EXISTS idx_world_events_payload_gin
    ON world_events USING gin (payload);

CREATE TABLE IF NOT EXISTS memory_snapshots (
    session_id text NOT NULL REFERENCES app_sessions(id) ON DELETE CASCADE,
    memory_id text NOT NULL,
    rule_id text NULL,
    memory_type text NOT NULL,
    memory_scope text NOT NULL,
    memory_layer text NOT NULL,
    last_operation text NOT NULL DEFAULT 'create',
    subject_id text NULL,
    owner_character_id text NULL,
    visible_to_character_ids text[] NOT NULL DEFAULT '{}',
    content text NOT NULL,
    source_event_ids text[] NOT NULL,
    source_memory_ids text[] NOT NULL DEFAULT '{}',
    salience double precision NOT NULL CHECK (salience >= 0 AND salience <= 1),
    confidence double precision NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    visibility text NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    last_updated_event_id text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (session_id, memory_id),
    CHECK (
        memory_layer = 'archival'
        OR metadata->>'non_authoritative' = 'true'
        OR array_length(source_event_ids, 1) IS NOT NULL
    ),
    CHECK (last_operation IN ('create', 'reinforce', 'revise', 'supersede', 'archive')),
    FOREIGN KEY (session_id, last_updated_event_id)
        REFERENCES world_events(session_id, id)
        DEFERRABLE INITIALLY DEFERRED
);

CREATE INDEX IF NOT EXISTS idx_memory_snapshots_owner
    ON memory_snapshots(session_id, owner_character_id);

CREATE INDEX IF NOT EXISTS idx_memory_snapshots_visible_gin
    ON memory_snapshots USING gin (visible_to_character_ids);

CREATE INDEX IF NOT EXISTS idx_memory_snapshots_metadata_gin
    ON memory_snapshots USING gin (metadata);

CREATE TABLE IF NOT EXISTS memory_operations (
    id bigserial PRIMARY KEY,
    session_id text NOT NULL REFERENCES app_sessions(id) ON DELETE CASCADE,
    memory_id text NOT NULL,
    operation text NOT NULL CHECK (
        operation IN ('create', 'reinforce', 'revise', 'supersede', 'archive')
    ),
    source_event_id text NOT NULL,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (session_id, memory_id)
        REFERENCES memory_snapshots(session_id, memory_id)
        DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY (session_id, source_event_id)
        REFERENCES world_events(session_id, id)
        DEFERRABLE INITIALLY DEFERRED
);

CREATE INDEX IF NOT EXISTS idx_memory_operations_memory
    ON memory_operations(session_id, memory_id, id);

CREATE TABLE IF NOT EXISTS character_impressions (
    session_id text NOT NULL REFERENCES app_sessions(id) ON DELETE CASCADE,
    observer_id text NOT NULL,
    target_id text NOT NULL,
    trust double precision NOT NULL CHECK (trust >= -1 AND trust <= 1),
    suspicion double precision NOT NULL CHECK (suspicion >= -1 AND suspicion <= 1),
    fear double precision NOT NULL CHECK (fear >= -1 AND fear <= 1),
    current_strategy text NULL,
    source_memory_ids text[] NOT NULL DEFAULT '{}',
    source_event_ids text[] NOT NULL DEFAULT '{}',
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    last_updated_event_id text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (session_id, observer_id, target_id),
    FOREIGN KEY (session_id, last_updated_event_id)
        REFERENCES world_events(session_id, id)
        DEFERRABLE INITIALLY DEFERRED
);

CREATE INDEX IF NOT EXISTS idx_character_impressions_source_events_gin
    ON character_impressions USING gin (source_event_ids);

CREATE TABLE IF NOT EXISTS character_fact_awareness (
    session_id text NOT NULL REFERENCES app_sessions(id) ON DELETE CASCADE,
    awareness_id text NOT NULL,
    character_id text NOT NULL,
    world_info_id text NOT NULL,
    stance text NOT NULL,
    confidence double precision NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    source_type text NOT NULL,
    source_refs text[] NOT NULL DEFAULT '{}',
    evidence_clue_ids text[] NOT NULL DEFAULT '{}',
    source_event_ids text[] NOT NULL DEFAULT '{}',
    last_updated_event_id text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (session_id, awareness_id),
    UNIQUE (session_id, character_id, world_info_id),
    FOREIGN KEY (session_id, last_updated_event_id)
        REFERENCES world_events(session_id, id)
        DEFERRABLE INITIALLY DEFERRED
);

CREATE INDEX IF NOT EXISTS idx_character_fact_awareness_character
    ON character_fact_awareness(session_id, character_id);

CREATE INDEX IF NOT EXISTS idx_character_fact_awareness_sources_gin
    ON character_fact_awareness USING gin (source_event_ids);

CREATE TABLE IF NOT EXISTS runtime_traces (
    id text PRIMARY KEY,
    session_id text NOT NULL REFERENCES app_sessions(id) ON DELETE CASCADE,
    action_event_id text NULL,
    target_character_id text NULL,
    backend text NOT NULL,
    memory_projection jsonb NOT NULL DEFAULT '{}'::jsonb,
    director_decision jsonb NOT NULL DEFAULT '{}'::jsonb,
    llm_error_type text NULL,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (session_id, action_event_id)
        REFERENCES world_events(session_id, id)
        DEFERRABLE INITIALLY DEFERRED
);

CREATE INDEX IF NOT EXISTS idx_runtime_traces_session_created
    ON runtime_traces(session_id, created_at);

CREATE INDEX IF NOT EXISTS idx_runtime_traces_payload_gin
    ON runtime_traces USING gin (payload);

CREATE TABLE IF NOT EXISTS idempotency_keys (
    session_id text NOT NULL REFERENCES app_sessions(id) ON DELETE CASCADE,
    idempotency_key text NOT NULL,
    request_hash text NOT NULL,
    response_event_ids text[] NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now(),
    committed_at timestamptz NULL,
    PRIMARY KEY (session_id, idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_idempotency_keys_created
    ON idempotency_keys(session_id, created_at);
