"""Centralized KB directory structure constants. All paths relative to KB root.

Structure:
  KB_ROOT/
  ├── _inbox/         Raw sources (hidden from Obsidian graph)
  ├── _meta/          Index, overview, log, schema (hidden, no wikilinks)
  ├── communities/    Community hub pages (with [[wikilinks]])
  ├── wiki/           All generated knowledge pages
  ├── .llmwiki/       Engine config + graph data
  └── 03_ops/         Operational artifacts (lint reports, etc.)
"""

INBOX_DIR = "_inbox"          # Was 01_raw
META_DIR = "_meta"            # index.md, overview.md, log.md, schema.md
WIKI_DIR = "wiki"             # All knowledge pages
COMMUNITIES_DIR = "communities"  # Community hub pages
LLMWIKI_DIR = ".llmwiki"      # Engine config
OPS_DIR = "operations"        # Operational artifacts (lint reports, etc.)
CACHE_DIR = ".cache"          # Parser cache

# Within _meta/ (prefixed with _ so Obsidian hides them from graph)
INDEX_FILE = "_index.md"
OVERVIEW_FILE = "_overview.md"
LOG_FILE = "_log.md"
SCHEMA_FILE = "schema.md"

# Wiki subdirectories
WIKI_SUBDIRS = [
    "sources", "entities", "concepts", "crystals",
    "comparisons", "synthesis", "findings", "thesis",
    "methodology", "queries",
]
