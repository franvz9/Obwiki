"""KB project templates — schema.md + purpose.md scaffolds.

Inspired by nashsu/llm_wiki src/lib/templates.ts
5 templates: Research, Reading, Personal, Business, General
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Template:
    id: str
    name: str
    description: str
    purpose: str
    schema_md: str
    extra_dirs: list[str] = field(default_factory=list)


TEMPLATES: list[Template] = []

# ── General (default) ────────────────────────────────────────

TEMPLATES.append(Template(
    id="general",
    name="General",
    description="通用知识库，适用于任何类型的知识积累",
    purpose="This wiki is a general-purpose knowledge base. Collect information, build understanding, and discover connections across any domain.",
    schema_md="""# Wiki Schema

## Page Types

| type | directory | naming | description |
|------|-----------|--------|-------------|
| source | wiki/sources/ | source-name.md | Source document summary |
| entity | wiki/entities/ | PascalCase.md | People, organizations, products |
| concept | wiki/concepts/ | kebab-case.md | Theories, methods, techniques |
| comparison | wiki/comparisons/ | a-vs-b.md | Side-by-side comparisons |
| synthesis | wiki/synthesis/ | topic-name.md | Cross-source synthesis |
| query | wiki/queries/ | query-name.md | Saved AI responses |
""",
    extra_dirs=["wiki/sources/", "wiki/entities/", "wiki/concepts/",
                 "wiki/comparisons/", "wiki/synthesis/", "wiki/queries/"],
))

# ── Research ─────────────────────────────────────────────────

TEMPLATES.append(Template(
    id="research",
    name="Research",
    description="深度研究项目，支持论文、实验数据、文献综述和论文写作",
    purpose="""This wiki supports a research project. Track the evolving thesis, maintain a structured literature review, and document findings as they emerge.

Key questions:
1. What is the central research question?
2. What evidence supports or challenges the current thesis?

Research scope: Document domain-specific concepts, methodologies, key findings, and open questions.""",
    schema_md="""# Wiki Schema

## Page Types

| type | directory | naming | description |
|------|-----------|--------|-------------|
| source | wiki/sources/ | author-year-title.md | Paper / source summary |
| entity | wiki/entities/ | PascalCase.md | Researchers, labs, institutions |
| concept | wiki/concepts/ | kebab-case.md | Theories, methods, phenomena |
| methodology | wiki/methodology/ | method-name.md | Experimental methods, protocols |
| finding | wiki/findings/ | finding-name.md | Key findings with evidence strength |
| thesis | wiki/thesis/ | thesis-name.md | Evolving thesis statements |
| comparison | wiki/comparisons/ | a-vs-b.md | Method / result comparisons |
| synthesis | wiki/synthesis/ | topic-name.md | Cross-paper synthesis |

## Frontmatter Extras
- `thesis` pages: `confidence` (high|medium|low), `status` (draft|reviewed|published)
- `finding` pages: `evidence_strength` (strong|moderate|weak), `source_count`
""",
    extra_dirs=["wiki/sources/", "wiki/entities/", "wiki/concepts/",
                 "wiki/methodology/", "wiki/findings/", "wiki/thesis/",
                 "wiki/comparisons/", "wiki/synthesis/"],
))

# ── Reading ──────────────────────────────────────────────────

TEMPLATES.append(Template(
    id="reading",
    name="Reading",
    description="读书笔记，按章节提取人物、主题、情节线索，构建书籍知识图谱",
    purpose="""This wiki tracks reading progress through a book. Build character profiles, theme pages, plot summaries, and chapter-by-chapter notes.

Reading goals:
1. Understand character arcs and relationships
2. Track themes and motifs across chapters
3. Build a companion wiki for the book""",
    schema_md="""# Wiki Schema

## Page Types

| type | directory | naming | description |
|------|-----------|--------|-------------|
| source | wiki/sources/ | chapter-XX.md | Chapter summary |
| entity | wiki/entities/ | CharacterName.md | Character profiles |
| concept | wiki/concepts/ | theme-name.md | Themes, motifs, symbols |
| comparison | wiki/comparisons/ | a-vs-b.md | Character / theme comparisons |
| synthesis | wiki/synthesis/ | topic-name.md | Cross-chapter analysis |
| finding | wiki/findings/ | clue-name.md | Plot clues / foreshadowing |
| query | wiki/queries/ | query-name.md | Discussion questions |

## Frontmatter Extras
- `entity` (character): `role` (protagonist|antagonist|supporting), `first_appearance`
- `concept` (theme): `frequency` (pervasive|recurring|minor)
""",
    extra_dirs=["wiki/sources/", "wiki/entities/", "wiki/concepts/",
                 "wiki/comparisons/", "wiki/synthesis/", "wiki/findings/"],
))

# ── Personal ─────────────────────────────────────────────────

TEMPLATES.append(Template(
    id="personal",
    name="Personal Growth",
    description="个人成长知识库，追踪目标、习惯、反思和学习笔记",
    purpose="""This wiki supports personal growth. Track goals, habits, journal entries, and self-improvement notes.

Focus areas:
1. Goals: What am I working toward?
2. Habits: What daily practices am I building?
3. Reflections: What am I learning about myself?

Build a structured picture of your growth over time.""",
    schema_md="""# Wiki Schema

## Page Types

| type | directory | naming | description |
|------|-----------|--------|-------------|
| source | wiki/sources/ | date-title.md | Journal / source entry |
| entity | wiki/entities/ | PersonName.md | People in your life |
| concept | wiki/concepts/ | concept-name.md | Ideas, techniques, frameworks |
| synthesis | wiki/synthesis/ | period-review.md | Monthly / quarterly reviews |
| query | wiki/queries/ | query-name.md | Self-reflection Q&A |

## Frontmatter Extras
- `source` (journal): `mood`, `energy` (1-10), `tags`
- `synthesis` (review): `period` (weekly|monthly|quarterly)
""",
    extra_dirs=["wiki/sources/", "wiki/entities/", "wiki/concepts/",
                 "wiki/synthesis/", "wiki/queries/"],
))

# ── Business ─────────────────────────────────────────────────

TEMPLATES.append(Template(
    id="business",
    name="Business",
    description="团队/项目知识库，管理会议记录、决策、项目文档和竞争分析",
    purpose="""This wiki serves as a team knowledge base. Capture meeting notes, project documents, decisions, and competitive analysis.

Key goals:
1. Keep the team aligned with up-to-date documentation
2. Track decisions and their rationale
3. Maintain a living competitive landscape""",
    schema_md="""# Wiki Schema

## Page Types

| type | directory | naming | description |
|------|-----------|--------|-------------|
| source | wiki/sources/ | date-type.md | Meeting notes, docs |
| entity | wiki/entities/ | CompanyName.md | Companies, competitors, partners |
| concept | wiki/concepts/ | strategy-name.md | Strategies, frameworks, methods |
| comparison | wiki/comparisons/ | a-vs-b.md | Competitive comparisons |
| synthesis | wiki/synthesis/ | quarterly-review.md | Periodic analysis |
| finding | wiki/findings/ | insight-name.md | Key insights / learnings |
| query | wiki/queries/ | topic-name.md | Research Q&A |

## Frontmatter Extras
- `source` (meeting): `date`, `attendees`, `decisions`
- `entity` (company): `sector`, `stage`, `relevance` (high|medium|low)
""",
    extra_dirs=["wiki/sources/", "wiki/entities/", "wiki/concepts/",
                 "wiki/comparisons/", "wiki/synthesis/", "wiki/findings/"],
))


def get_template(template_id: str) -> Template | None:
    for t in TEMPLATES:
        if t.id == template_id:
            return t
    return None


def list_templates() -> list[dict]:
    return [
        {"id": t.id, "name": t.name, "description": t.description}
        for t in TEMPLATES
    ]
