-- Enable pgvector extension to support semantic search.
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    display_name TEXT,
    credentials JSONB NOT NULL,
    daily_limit INTEGER DEFAULT 50,
    rate_delay INTERVAL DEFAULT INTERVAL '5 minutes',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS tweets (
    id BIGSERIAL PRIMARY KEY,
    tweet_id TEXT NOT NULL UNIQUE,
    author_handle TEXT NOT NULL,
    content TEXT NOT NULL,
    language VARCHAR(10),
    like_count INTEGER DEFAULT 0,
    reply_count INTEGER DEFAULT 0,
    retweet_count INTEGER DEFAULT 0,
    scraped_at TIMESTAMPTZ DEFAULT NOW(),
    raw_payload JSONB
);

CREATE TABLE IF NOT EXISTS replies (
    id BIGSERIAL PRIMARY KEY,
    tweet_id TEXT NOT NULL REFERENCES tweets(tweet_id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    body TEXT NOT NULL,
    embedding VECTOR(384),
    safety_score NUMERIC(4,3),
    generated_at TIMESTAMPTZ DEFAULT NOW(),
    metadata JSONB
);

CREATE TABLE IF NOT EXISTS actions (
    id BIGSERIAL PRIMARY KEY,
    action_type TEXT NOT NULL,
    tweet_id TEXT REFERENCES tweets(tweet_id) ON DELETE SET NULL,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    status TEXT NOT NULL,
    details JSONB,
    executed_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tweets_scraped_at ON tweets (scraped_at DESC);
CREATE INDEX IF NOT EXISTS idx_replies_embedding ON replies USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);
CREATE INDEX IF NOT EXISTS idx_actions_executed_at ON actions (executed_at DESC);
