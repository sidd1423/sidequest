-- Sidequest example-quest library on Tiger Data (Postgres + pgvector).
-- Run once in the Tiger console SQL editor, or let `python -m tiger.seed` do it for you.
--
-- The embedding dimension (768) must match EMBEDDING_DIM in .env.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS quests (
    id                BIGSERIAL PRIMARY KEY,
    quest_text        TEXT        NOT NULL UNIQUE,
    category          TEXT        NOT NULL,
    duration_minutes  INTEGER     NOT NULL CHECK (duration_minutes > 0),
    difficulty        TEXT        NOT NULL CHECK (difficulty IN ('easy', 'moderate', 'challenging', 'extreme')),
    tags              TEXT[]      NOT NULL DEFAULT '{}',
    embedding         VECTOR(768),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Approximate nearest-neighbour index for cosine similarity search.
CREATE INDEX IF NOT EXISTS quests_embedding_hnsw
    ON quests USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS quests_category_idx ON quests (category);
