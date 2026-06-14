"""Wiki Schema — parses schema.md to drive page type routing and validation.

Inspired by nashsu/llm_wiki src/lib/wiki-page-types.ts + src/lib/wiki-schema.ts

schema.md format (in .llmwiki/schema.md):
  ## Page Types
  | type       | directory          | naming          |
  |------------|-------------------|-----------------|
  | source     | wiki/sources/      | source-name.md  |
  | entity     | wiki/entities/     | PascalCase.md   |
  ...
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml


DEFAULT_TYPES: list[dict] = [
    {"type": "source",     "directory": "wiki/sources/",      "naming": "source-name.md"},
    {"type": "entity",     "directory": "wiki/entities/",     "naming": "PascalCase.md"},
    {"type": "concept",    "directory": "wiki/concepts/",     "naming": "kebab-case.md"},
    {"type": "comparison", "directory": "wiki/comparisons/",  "naming": "a-vs-b.md"},
    {"type": "synthesis",  "directory": "wiki/synthesis/",    "naming": "topic-name.md"},
    {"type": "finding",    "directory": "wiki/findings/",     "naming": "finding-name.md"},
    {"type": "thesis",     "directory": "wiki/thesis/",       "naming": "thesis-name.md"},
    {"type": "query",      "directory": "wiki/queries/",      "naming": "query-name.md"},
    {"type": "crystal",    "directory": "wiki/crystals/",     "naming": "crystal-name.md"},
]

DEFAULT_SCHEMA_MD = """# Wiki Schema

## Page Types

| type | directory | naming | description |
|------|-----------|--------|-------------|
| source | wiki/sources/ | source-name.md | Source document summary |
| entity | wiki/entities/ | PascalCase.md | People, organizations, products, datasets |
| concept | wiki/concepts/ | kebab-case.md | Theories, methods, techniques, phenomena |
| comparison | wiki/comparisons/ | a-vs-b.md | Side-by-side comparisons |
| synthesis | wiki/synthesis/ | topic-name.md | Cross-source synthesis |
| finding | wiki/findings/ | finding-name.md | Research findings / key evidence |
| thesis | wiki/thesis/ | thesis-name.md | Evolving thesis |
| query | wiki/queries/ | query-name.md | Saved AI responses |
| crystal | wiki/crystals/ | crystal-name.md | LLM-synthesized knowledge crystals |

## Naming Conventions

- **PascalCase**: EntityName.md (e.g., `OpenAI.md`)
- **kebab-case**: concept-name.md (e.g., `self-attention.md`)
- **source-name**: original filename without extension (e.g., `paper-title.md`)

## Cross-Reference Rules

- Use `[[wiki/path/to/page]]` for cross-references
- Always include `sources:` in frontmatter when the page is derived from a raw source
- Use `related:` frontmatter array for soft links

## Contradiction Handling

When two pages make conflicting claims:
1. Add a `## Contradictions` section to both pages
2. Link them bidirectionally via `related:`
3. Create a `wiki/comparisons/` page if the conflict is significant
"""


class WikiSchema:
    def __init__(self, type_table: list[dict]):
        self.types = type_table
        self._type_to_dir = {t["type"]: t["directory"] for t in type_table}
        self._dir_to_type: dict[str, str] = {}
        for t in type_table:
            d = t["directory"].rstrip("/").replace("wiki/", "")
            self._dir_to_type[d] = t["type"]

    @classmethod
    def from_kb(cls, kb_root: str) -> "WikiSchema":
        return parse_schema(kb_root)

    @classmethod
    def default(cls) -> "WikiSchema":
        return cls(DEFAULT_TYPES)

    def get_directory(self, page_type: str) -> str:
        return self._type_to_dir.get(page_type, f"wiki/{page_type}s/")

    def infer_type_from_path(self, path: str) -> Optional[str]:
        """Infer page type from its directory path."""
        normalized = path.replace("\\", "/").lower()
        for t in self.types:
            d = t["directory"].rstrip("/").lower()
            if f"/{d}/" in f"/{normalized}/":
                return t["type"]

        parts = normalized.split("/")
        if len(parts) >= 3 and parts[0] == "wiki":
            return parts[1]  # custom directory → type
        return None

    def validate_page(self, path: str, frontmatter: dict) -> Optional[str]:
        """Validate that page path matches its frontmatter type. Returns error message or None."""
        page_type = frontmatter.get("type", "")
        if not page_type:
            return None  # no type to validate

        inferred = self.infer_type_from_path(path)
        if inferred and inferred != page_type:
            expected_dir = self.get_directory(page_type)
            return f"Page at {path} has type '{page_type}' but is in directory for '{inferred}'. Expected: {expected_dir}"
        return None

    def to_yaml(self) -> str:
        return yaml.dump({"types": self.types}, allow_unicode=True, default_flow_style=False)


def parse_schema(kb_root: str) -> WikiSchema:
    """Parse schema.md from a knowledge base root. Falls back to defaults."""
    from ..paths import META_DIR, SCHEMA_FILE
    schema_path = Path(kb_root) / META_DIR / SCHEMA_FILE
    if not schema_path.exists():
        return WikiSchema(DEFAULT_TYPES)

    content = schema_path.read_text(encoding="utf-8")
    types = _parse_markdown_table(content)
    return WikiSchema(types) if types else WikiSchema(DEFAULT_TYPES)


def _parse_markdown_table(content: str) -> list[dict]:
    """Parse a simple markdown table with | type | directory | naming | columns."""
    lines = content.split("\n")
    types = []
    in_header = False
    header_cols = []

    for line in lines:
        line = line.strip()
        if not line.startswith("|") or not line.endswith("|"):
            continue
        cells = [c.strip() for c in line[1:-1].split("|")]

        # Skip separator lines like |---|---|
        if all(c.replace("-", "").replace(":", "").strip() == "" for c in cells):
            in_header = False  # header done
            continue

        if not in_header and not header_cols:
            # First row is header
            header_cols = cells
            in_header = True
            continue
        elif in_header:
            # This is a data row if it's right after header and not a separator
            pass

        if header_cols and len(cells) >= 2:
            row = {}
            for i, col in enumerate(header_cols):
                if i < len(cells):
                    row[col] = cells[i]
            if row.get("type") and row.get("directory"):
                types.append(row)

    return types


def find_wiki_dir(root: str | Path) -> Path | None:
    """Find the wiki directory in a KB root."""
    from ..paths import WIKI_DIR
    root = Path(root)
    d = root / WIKI_DIR
    if d.exists() and d.is_dir():
        return d
    return None


def write_default_schema(kb_root: str) -> str:
    """Write default schema.md to a knowledge base. Returns the path."""
    from ..paths import META_DIR, SCHEMA_FILE
    schema_dir = Path(kb_root) / META_DIR
    schema_dir.mkdir(parents=True, exist_ok=True)
    schema_path = schema_dir / SCHEMA_FILE
    schema_path.write_text(DEFAULT_SCHEMA_MD, encoding="utf-8")
    return str(schema_path)
