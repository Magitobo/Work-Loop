import re
from pathlib import Path

import pytest

from workloop.core import WorkLoop
from workloop.scaffold import (
    MANAGED_END_MARKER,
    MANAGED_START_MARKER,
    USER_DOCS,
    extract_managed_block,
    managed_doc_header,
    scaffold_vault,
    sync_agents_md,
    sync_work_md_howto,
)


def test_extract_managed_block():
    template = f"""# Title
Some prefix
{MANAGED_START_MARKER}
## 1. Rules
- Rule A
{MANAGED_END_MARKER}
Some suffix"""
    block = extract_managed_block(template)
    assert block.startswith(MANAGED_START_MARKER)
    assert block.endswith(MANAGED_END_MARKER)
    assert "## 1. Rules" in block
    assert "Some prefix" not in block


def test_sync_agents_md_creates_new(tmp_path: Path):
    agents_path = tmp_path / "AGENTS.md"
    template_path = tmp_path / "template-AGENTS.md"
    template_path.write_text(f"{MANAGED_START_MARKER}\n## Rules\n{MANAGED_END_MARKER}")

    changed = sync_agents_md(agents_path, template_path)
    assert changed is True
    assert agents_path.exists()
    content = agents_path.read_text()
    assert "Personal Vault Rules" in content
    assert "## Rules" in content


def test_sync_agents_md_replaces_marker_block(tmp_path: Path):
    agents_path = tmp_path / "AGENTS.md"
    template_path = tmp_path / "template-AGENTS.md"

    # User has custom rules before and after
    agents_path.write_text(f"""# Custom User Header
User custom notes before

{MANAGED_START_MARKER}
## Old Rules v1
{MANAGED_END_MARKER}

# User custom notes after
Keep this safe!""")

    template_path.write_text(f"{MANAGED_START_MARKER}\n## New Rules v2\n{MANAGED_END_MARKER}")

    changed = sync_agents_md(agents_path, template_path)
    assert changed is True

    updated_content = agents_path.read_text()
    assert "User custom notes before" in updated_content
    assert "User custom notes after" in updated_content
    assert "Keep this safe!" in updated_content
    assert "## New Rules v2" in updated_content
    assert "## Old Rules v1" not in updated_content


def test_sync_agents_md_appends_when_no_markers(tmp_path: Path):
    agents_path = tmp_path / "AGENTS.md"
    template_path = tmp_path / "template-AGENTS.md"

    agents_path.write_text("# Existing User AGENTS.md\nNo markers here.")
    template_path.write_text(f"{MANAGED_START_MARKER}\n## Injected Rules\n{MANAGED_END_MARKER}")

    changed = sync_agents_md(agents_path, template_path)
    assert changed is True

    updated = agents_path.read_text()
    assert "# Existing User AGENTS.md" in updated
    assert "No markers here." in updated
    assert "## Injected Rules" in updated
    assert MANAGED_START_MARKER in updated


def test_sync_agents_md_idempotent(tmp_path: Path):
    agents_path = tmp_path / "AGENTS.md"
    template_path = tmp_path / "template-AGENTS.md"

    template_path.write_text(f"{MANAGED_START_MARKER}\n## Current Rules\n{MANAGED_END_MARKER}")
    sync_agents_md(agents_path, template_path)

    # Second call should make no changes
    changed = sync_agents_md(agents_path, template_path)
    assert changed is False


def test_scaffold_vault_full(tmp_path: Path):
    script_dir = Path(__file__).parent.parent
    vault_dir = tmp_path / "MyVault"
    work_dir = vault_dir / "02-Work-Loop-Items"

    res = scaffold_vault(work_dir=work_dir, script_dir=script_dir, vault_dir=vault_dir)

    assert (vault_dir / "00 Inbox").is_dir()
    assert (vault_dir / "03 Verified Research").is_dir()
    assert (vault_dir / "50 Raw").is_dir()
    assert (vault_dir / "AGENTS.md").is_file()
    assert (vault_dir / "03 Verified Research" / "README.md").is_file()
    assert (vault_dir / ".agents" / "skills" / "verified-research" / "SKILL.md").is_file()
    assert (vault_dir / ".agents" / "skills" / "synthesize-research" / "SKILL.md").is_file()
    assert (vault_dir / ".opencode" / "skills" / "verified-research" / "SKILL.md").is_file()
    assert (vault_dir / ".claude" / "skills" / "synthesize-research" / "SKILL.md").is_file()
    assert (work_dir / "WORK.md").is_file()
    assert len(res['created']) >= 5

    # Re-running scaffold should be idempotent (no new created files)
    res2 = scaffold_vault(work_dir=work_dir, script_dir=script_dir, vault_dir=vault_dir)
    assert len(res2['created']) == 0
    assert len(res2['updated']) == 0


def test_scaffold_vault_readme_syncs_template_changes(tmp_path: Path):
    script_dir = Path(__file__).parent.parent
    vault_dir = tmp_path / "MyVault"
    work_dir = vault_dir / "02-Work-Loop-Items"

    scaffold_vault(work_dir=work_dir, script_dir=script_dir, vault_dir=vault_dir)
    readme = vault_dir / "03 Verified Research" / "README.md"
    template = script_dir / "templates" / "VERIFIED-RESEARCH-README.md"
    assert readme.read_text() == template.read_text()

    # Simulate drift in the vault copy
    readme.write_text(readme.read_text() + "\n<!-- local drift -->\n")

    res = scaffold_vault(work_dir=work_dir, script_dir=script_dir, vault_dir=vault_dir)
    assert str(readme) in res['updated']
    assert readme.read_text() == template.read_text()


def test_scaffold_vault_mirrors_user_docs(tmp_path: Path):
    script_dir = Path(__file__).parent.parent
    vault_dir = tmp_path / "MyVault"
    work_dir = vault_dir / "02-Work-Loop-Items"

    res = scaffold_vault(work_dir=work_dir, script_dir=script_dir, vault_dir=vault_dir)
    for rel in USER_DOCS:
        dst = work_dir / rel
        assert str(dst) in res['created']
        assert dst.read_text() == managed_doc_header(rel) + (script_dir / rel).read_text()

    # Local edits are overwritten on the next start
    tutorial = work_dir / "docs" / "TUTORIAL.md"
    tutorial.write_text(tutorial.read_text() + "\nlocal edit\n")
    res = scaffold_vault(work_dir=work_dir, script_dir=script_dir, vault_dir=vault_dir)
    assert res['updated'] == [str(tutorial)]
    assert "local edit" not in tutorial.read_text()


def test_user_doc_links_resolve_in_vault(tmp_path: Path):
    """Relative links in WORK.md and the mirrored docs must point at files that exist in the vault."""
    script_dir = Path(__file__).parent.parent
    work_dir = tmp_path / "MyVault" / "02-Work-Loop-Items"
    scaffold_vault(work_dir=work_dir, script_dir=script_dir, vault_dir=tmp_path / "MyVault")

    link_re = re.compile(r"\]\(([^)#\s]+\.md)(?:#[^)]*)?\)")
    checked = 0
    for rel in ("WORK.md", *USER_DOCS):
        doc = work_dir / rel
        # Examples in code blocks and inline code are not real links
        text = re.sub(r"```.*?```|`[^`\n]*`", "", doc.read_text(), flags=re.DOTALL)
        for target in link_re.findall(text):
            if target.startswith(("http:", "https:")):
                continue
            assert (doc.parent / target).resolve().is_file(), f"{rel} links to missing {target}"
            checked += 1
    assert checked >= 3


_OLD_VAULT_WORK_MD = """\
# Work Loop

## How to use

### How to Dispatch Work
- old instructions

### Child Agents & Research
- **Verified research:** Path A / Path B

## Add New Item
- [ ] _Add new instructions here_

<!-- WORK-LOOP:NEEDS-ATTENTION:BEGIN -->
## Needs Attention
- **ITEM-1** (needs-review). [Open conversation](ITEM-1/CONVERSATION.md)
<!-- WORK-LOOP:NEEDS-ATTENTION:END -->

## Active Items

| Task / Conversation | Status | Last Updated | Log | ID |
| ------------------- | :----: | :----------: | :-: | -- |
| [Item one](ITEM-1/CONVERSATION.md) | needs-review | 2026-09-20 | | ITEM-1 |

## Done

| Task / Conversation | Last Updated | Log | ID |
| ------------------- | :----------: | :-: | -- |
"""


def _template_howto_block(script_dir: Path) -> str:
    text = (script_dir / "templates" / "WORK.md").read_text()
    return text[text.index("<!-- WORK-LOOP:HOWTO:START"):text.index("<!-- WORK-LOOP:HOWTO:END -->")]


def test_sync_work_md_howto_replaces_unfenced_section(tmp_path: Path):
    script_dir = Path(__file__).parent.parent
    work_md = tmp_path / "WORK.md"
    work_md.write_text(_OLD_VAULT_WORK_MD)

    assert sync_work_md_howto(work_md, script_dir / "templates" / "WORK.md") is True
    text = work_md.read_text()
    assert _template_howto_block(script_dir) in text
    assert "Path A" not in text and "### How to Dispatch Work" not in text
    # Everything from Add New Item onwards is untouched
    tail = _OLD_VAULT_WORK_MD[_OLD_VAULT_WORK_MD.index("## Add New Item"):]
    assert text.endswith(tail)
    assert text.startswith("# Work Loop\n\n<!-- WORK-LOOP:HOWTO:START")
    assert "<!-- WORK-LOOP:HOWTO:END -->\n\n## Add New Item" in text

    # Second run is a no-op
    assert sync_work_md_howto(work_md, script_dir / "templates" / "WORK.md") is False


def test_sync_work_md_howto_replaces_fenced_section(tmp_path: Path):
    script_dir = Path(__file__).parent.parent
    work_md = tmp_path / "WORK.md"
    work_md.write_text(
        "# Work Loop\n\n"
        "<!-- WORK-LOOP:HOWTO:START -->\n## How to use\n- stale\n<!-- WORK-LOOP:HOWTO:END -->\n\n"
        "## Add New Item\n- [ ] mine\n"
    )
    assert sync_work_md_howto(work_md, script_dir / "templates" / "WORK.md") is True
    text = work_md.read_text()
    assert "- stale" not in text
    assert _template_howto_block(script_dir) in text
    assert text.endswith("<!-- WORK-LOOP:HOWTO:END -->\n\n## Add New Item\n- [ ] mine\n")


def test_sync_work_md_howto_inserts_after_title_when_missing(tmp_path: Path):
    script_dir = Path(__file__).parent.parent
    work_md = tmp_path / "WORK.md"
    work_md.write_text("# Work Loop\n\n## Add New Item\n- [ ] mine\n")
    assert sync_work_md_howto(work_md, script_dir / "templates" / "WORK.md") is True
    text = work_md.read_text()
    assert text.startswith("# Work Loop\n\n<!-- WORK-LOOP:HOWTO:START")
    assert text.endswith("<!-- WORK-LOOP:HOWTO:END -->\n\n## Add New Item\n- [ ] mine\n")


def test_scaffold_vault_updates_howto_in_existing_work_md(tmp_path: Path):
    script_dir = Path(__file__).parent.parent
    vault_dir = tmp_path / "MyVault"
    work_dir = vault_dir / "02-Work-Loop-Items"
    work_dir.mkdir(parents=True)
    work_md = work_dir / "WORK.md"
    work_md.write_text(_OLD_VAULT_WORK_MD)

    res = scaffold_vault(work_dir=work_dir, script_dir=script_dir, vault_dir=vault_dir)
    assert str(work_md) in res['updated']
    assert "](docs/TUTORIAL.md)" in work_md.read_text()


def test_workloop_init_triggers_scaffold(tmp_path: Path):
    script_dir = Path(__file__).parent.parent
    vault_dir = tmp_path / "AutoVault"
    work_dir = vault_dir / "02-Work-Loop-Items"
    work_dir.mkdir(parents=True)

    config = {
        "work_dir": str(work_dir),
        "harness": {"type": "claude", "max_budget_usd": 5.0},
    }

    wl = WorkLoop(config, script_dir=script_dir)
    assert hasattr(wl, 'scaffold_actions')
    assert (vault_dir / "AGENTS.md").is_file()
    assert (vault_dir / "03 Verified Research" / "README.md").is_file()
    assert (work_dir / "WORK.md").is_file()


def test_extract_readme_sections_all(tmp_path: Path):
    from workloop.scaffold import extract_readme_section

    readme_content = """# Guidelines
## 1. Core Architecture & Philosophy
Architecture content here.
---
## 2. Standard Note Template
```markdown
---
topic: {Topic Name}
---
```
---
## 3. Verification Rules for Authors & Agents
Rules content here.
"""
    sec1 = extract_readme_section(readme_content, 1)
    assert "Architecture content here." in sec1
    assert "Standard Note Template" not in sec1

    sec2 = extract_readme_section(readme_content, 2)
    assert "topic: {Topic Name}" in sec2
    assert "Architecture" not in sec2

    sec3 = extract_readme_section(readme_content, 3)
    assert "Rules content here." in sec3


def test_real_template_headings_match_regexes():
    """Guard: fail fast if someone renames a heading in the real template.

    extract_readme_section() uses exact heading regexes.  If the headings in
    templates/VERIFIED-RESEARCH-README.md drift, sections silently resolve to
    '' and the LLM gets a broken prompt.  This test catches that at CI time.
    """
    from workloop.scaffold import extract_readme_section

    template_path = Path(__file__).parent.parent / "templates" / "VERIFIED-RESEARCH-README.md"
    readme = template_path.read_text(encoding="utf-8")

    sec1 = extract_readme_section(readme, 1)
    assert sec1, "Section 1 (Architecture & Philosophy) resolved to empty — heading renamed?"

    sec2 = extract_readme_section(readme, 2)
    assert sec2, "Section 2 (Standard Note Template) resolved to empty — heading renamed?"

    sec3 = extract_readme_section(readme, 3)
    assert sec3, "Section 3 (Verification Rules) resolved to empty — heading renamed?"


def test_render_template_placeholders_replaces_all_anchors(tmp_path: Path):
    from workloop.scaffold import render_template_placeholders

    dummy_script_dir = tmp_path / "repo"
    templates_dir = dummy_script_dir / "templates"
    templates_dir.mkdir(parents=True)
    (templates_dir / "VERIFIED-RESEARCH-README.md").write_text("""# Guidelines
## 1. Core Architecture & Philosophy
1. Layered Single-Note Model
---
## 2. Standard Note Template
```markdown
---
topic: {Topic Name}
---
```
---
## 3. Verification Rules for Authors & Agents
1. No Assertion Without Fetching
""")

    agent_template = """---
name: verified-research
---
## Architecture
{{templates/VERIFIED-RESEARCH-README.md#1}}

## Template
```
{{templates/VERIFIED-RESEARCH-README.md#2}}
```

## Rules
{{templates/VERIFIED-RESEARCH-README.md#3}}
"""

    rendered = render_template_placeholders(agent_template, dummy_script_dir)
    assert "Layered Single-Note Model" in rendered
    assert "topic: {Topic Name}" in rendered
    assert "No Assertion Without Fetching" in rendered
    assert "{{" not in rendered


def test_sync_agent_dir_renders_note_template(tmp_path: Path):
    script_dir = Path(__file__).parent.parent
    work_dir = tmp_path / "workspace"
    work_dir.mkdir(parents=True)

    config = {
        "work_dir": str(work_dir),
        "harness": {"type": "opencode", "max_budget_usd": 5.0},
    }
    wl = WorkLoop(config, script_dir=script_dir)
    wl._sync_agent_dir(str(work_dir))

    target_agent = work_dir / ".opencode" / "agents" / "verified-research.md"
    assert target_agent.is_file()
    rendered_content = target_agent.read_text()
    assert "{{" not in rendered_content
    assert "Layered Single-Note Model" in rendered_content
    assert "last-researched:" in rendered_content
    assert "No Assertion Without Fetching & Quoting" in rendered_content


def test_render_raises_on_missing_template(tmp_path: Path):
    from workloop.scaffold import render_template_placeholders

    text = "Prompt: {{templates/nonexistent.md#1}}"
    with pytest.raises(ValueError, match="missing file"):
        render_template_placeholders(text, tmp_path)


def test_render_raises_on_empty_section(tmp_path: Path):
    from workloop.scaffold import render_template_placeholders

    templates_dir = tmp_path / "templates"
    templates_dir.mkdir()
    (templates_dir / "VERIFIED-RESEARCH-README.md").write_text(
        "## 1. Totally Renamed Heading\nContent\n"
    )

    text = "Prompt: {{templates/VERIFIED-RESEARCH-README.md#1}}"
    with pytest.raises(ValueError, match="resolved to empty"):
        render_template_placeholders(text, tmp_path)
