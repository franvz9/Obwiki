from __future__ import annotations

import aiosqlite

from .config import settings


async def get_db() -> aiosqlite.Connection:
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(str(settings.db_path))
    db.row_factory = aiosqlite.Row
    await _migrate(db)
    return db


async def _migrate(db: aiosqlite.Connection) -> None:
    await db.executescript("""
        CREATE TABLE IF NOT EXISTS knowledge_bases (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            root_path TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL DEFAULT 'idle',
            config TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            kb_id TEXT NOT NULL REFERENCES knowledge_bases(id),
            type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            payload TEXT NOT NULL DEFAULT '{}',
            progress INTEGER NOT NULL DEFAULT 0,
            token_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            started_at TEXT,
            finished_at TEXT,
            log TEXT NOT NULL DEFAULT ''
        );

        CREATE INDEX IF NOT EXISTS idx_jobs_kb_id ON jobs(kb_id);
        CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);

        -- FTS5 index for file content search
        CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
            kb_id, path, title, content, tokenize='unicode61'
        );

        -- Separate table for content hashes (FTS5 has no extra columns)
        CREATE TABLE IF NOT EXISTS file_hashes (
            kb_id TEXT NOT NULL,
            path TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            PRIMARY KEY (kb_id, path)
        );

        -- Source lifecycle registry: tracks every imported file's processing state
        CREATE TABLE IF NOT EXISTS sources (
            id TEXT PRIMARY KEY,
            kb_id TEXT NOT NULL REFERENCES knowledge_bases(id),
            path TEXT NOT NULL,
            file_name TEXT NOT NULL,
            file_type TEXT NOT NULL,
            file_size INTEGER NOT NULL DEFAULT 0,
            content_hash TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'raw',
            wiki_pages TEXT NOT NULL DEFAULT '[]',
            error_log TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            modified_at TEXT NOT NULL DEFAULT (datetime('now')),
            indexed_at TEXT,
            extracted_at TEXT,
            UNIQUE(kb_id, path)
        );

        CREATE INDEX IF NOT EXISTS idx_sources_kb_id ON sources(kb_id);
        CREATE INDEX IF NOT EXISTS idx_sources_status ON sources(kb_id, status);

        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS token_usage (
            date TEXT PRIMARY KEY,
            tokens_used INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS provider_configs (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            provider TEXT NOT NULL,
            endpoint TEXT NOT NULL,
            api_key TEXT NOT NULL DEFAULT '',
            models TEXT NOT NULL DEFAULT '[]',
            is_default_text INTEGER NOT NULL DEFAULT 0,
            is_default_vision INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)
    await db.commit()
