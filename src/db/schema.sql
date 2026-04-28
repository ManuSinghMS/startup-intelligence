-- Startup Intelligence Platform Schema

-- Startups imported from Monday.com board
CREATE TABLE IF NOT EXISTS startups (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    legal_name TEXT,
    website TEXT,
    contact_email TEXT,
    contact_name TEXT,
    founder_name TEXT,
    cofounder_name TEXT,
    founder_linkedin_url TEXT,
    cofounder_linkedin_url TEXT,
    description TEXT,
    industry TEXT,
    secondary_industry TEXT,
    linkedin_url TEXT,
    twitter_handle TEXT,
    instagram_handle TEXT,
    stage TEXT,
    status TEXT,
    program_stream TEXT,
    tag TEXT CHECK(tag IN ('active', 'alumni', 'not_active')) DEFAULT 'active',
    last_ingested_at TIMESTAMP,
    sales_nav_checked_at TIMESTAMP,
    sales_nav_status TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Sources to monitor (RSS feeds, news sites, social accounts)
CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    url TEXT,
    rss_feed_url TEXT,
    type TEXT NOT NULL CHECK(type IN ('news', 'newsletter', 'social', 'press', 'blog')),
    priority INTEGER DEFAULT 3 CHECK(priority BETWEEN 1 AND 5),
    is_active INTEGER DEFAULT 1,
    last_fetched_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Content items collected from various sources.
-- NOTE: classification has no CHECK constraint — it carries either a news
-- category (funding/product_launch/...) OR a LinkedIn URL kind
-- (founder_post_url, company_activity_page, news_mention, etc.).
CREATE TABLE IF NOT EXISTS content_items (
    id TEXT PRIMARY KEY,
    startup_id TEXT,
    source_id TEXT,
    source_type TEXT NOT NULL,
    source_name TEXT,
    external_source TEXT,
    url TEXT,
    canonical_url TEXT,
    title TEXT,
    author_name TEXT,
    published_at TIMESTAMP,
    post_date TIMESTAMP,
    discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    raw_content TEXT,
    summary TEXT,
    classification TEXT,
    sentiment TEXT,
    impact_score REAL DEFAULT 0.0,
    topics TEXT,
    metadata_json TEXT,
    content_hash TEXT UNIQUE,
    confidence_score REAL DEFAULT 1.0,
    is_relevant INTEGER DEFAULT 1,
    hired_count INTEGER DEFAULT 0,
    ingestion_status TEXT DEFAULT 'full_content',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (startup_id) REFERENCES startups(id),
    FOREIGN KEY (source_id) REFERENCES sources(id)
);

-- Full-text search virtual table
CREATE VIRTUAL TABLE IF NOT EXISTS content_fts USING fts5(
    title,
    raw_content,
    summary,
    source_name,
    content='content_items',
    content_rowid='rowid'
);

-- Triggers to keep FTS index in sync
CREATE TRIGGER IF NOT EXISTS content_ai AFTER INSERT ON content_items BEGIN
    INSERT INTO content_fts(rowid, title, raw_content, summary, source_name)
    VALUES (new.rowid, new.title, new.raw_content, new.summary, new.source_name);
END;

CREATE TRIGGER IF NOT EXISTS content_ad AFTER DELETE ON content_items BEGIN
    INSERT INTO content_fts(content_fts, rowid, title, raw_content, summary, source_name)
    VALUES ('delete', old.rowid, old.title, old.raw_content, old.summary, old.source_name);
END;

CREATE TRIGGER IF NOT EXISTS content_au AFTER UPDATE ON content_items BEGIN
    INSERT INTO content_fts(content_fts, rowid, title, raw_content, summary, source_name)
    VALUES ('delete', old.rowid, old.title, old.raw_content, old.summary, old.source_name);
    INSERT INTO content_fts(rowid, title, raw_content, summary, source_name)
    VALUES (new.rowid, new.title, new.raw_content, new.summary, new.source_name);
END;

-- Many-to-many: which sources are relevant to which startups
CREATE TABLE IF NOT EXISTS startup_sources (
    startup_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    PRIMARY KEY (startup_id, source_id),
    FOREIGN KEY (startup_id) REFERENCES startups(id),
    FOREIGN KEY (source_id) REFERENCES sources(id)
);

-- AI-generated summaries (cached)
CREATE TABLE IF NOT EXISTS summaries (
    id TEXT PRIMARY KEY,
    startup_id TEXT,
    summary_type TEXT NOT NULL CHECK(summary_type IN (
        'company_7day', 'company_30day', 'weekly_digest',
        'market_snapshot', 'custom'
    )),
    content TEXT NOT NULL,
    period_start TIMESTAMP,
    period_end TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (startup_id) REFERENCES startups(id)
);

-- Ingestion job log
CREATE TABLE IF NOT EXISTS ingestion_logs (
    id TEXT PRIMARY KEY,
    source_id TEXT,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    items_found INTEGER DEFAULT 0,
    items_new INTEGER DEFAULT 0,
    items_duplicate INTEGER DEFAULT 0,
    status TEXT DEFAULT 'running',
    error_message TEXT,
    FOREIGN KEY (source_id) REFERENCES sources(id)
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_content_startup ON content_items(startup_id);
CREATE INDEX IF NOT EXISTS idx_content_published ON content_items(published_at);
CREATE INDEX IF NOT EXISTS idx_content_classification ON content_items(classification);
CREATE INDEX IF NOT EXISTS idx_content_source_type ON content_items(source_type);
CREATE INDEX IF NOT EXISTS idx_content_hash ON content_items(content_hash);
CREATE INDEX IF NOT EXISTS idx_content_canonical ON content_items(canonical_url);
CREATE INDEX IF NOT EXISTS idx_startups_name ON startups(name);
CREATE INDEX IF NOT EXISTS idx_startups_tag ON startups(tag);
