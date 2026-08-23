import pytest
from pathlib import Path
from workloop.scaffold import (
    MANAGED_START_MARKER,
    MANAGED_END_MARKER,
    extract_managed_block,
    sync_agents_md,
    scaffold_vault,
)
from workloop.core import WorkLoop


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


def test_render_verified_research_agent_replaces_all_anchors(tmp_path: Path):
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
