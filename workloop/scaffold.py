import re
import shutil
from pathlib import Path

MANAGED_START_MARKER = "<!-- WORK-LOOP:START — DO NOT EDIT THIS BLOCK MANUALLY -->"
MANAGED_END_MARKER = "<!-- WORK-LOOP:END -->"
MANAGED_RE = re.compile(
    r"<!--\s*WORK-LOOP:START.*?-->.*?<!--\s*WORK-LOOP:END\s*-->",
    re.DOTALL | re.IGNORECASE,
)


def extract_managed_block(template_text: str) -> str:
    """Extract the managed block including markers from template_text."""
    match = MANAGED_RE.search(template_text)
    if match:
        return match.group(0).strip()
    return f"{MANAGED_START_MARKER}\n{template_text.strip()}\n{MANAGED_END_MARKER}"


def extract_readme_section(readme_text: str, section: str | int) -> str:
    """Extract a specific section from VERIFIED-RESEARCH-README.md.

    - section 1 / '1' / 'architecture': Section 1 (Core Architecture & Philosophy)
    - section 2 / '2' / 'template': Section 2 (Standard Note Template code block)
    - section 3 / '3' / 'rules': Section 3 (Verification Rules)
    """
    sec = str(section).strip().lower()
    if sec in ("1", "architecture"):
        m = re.search(r"## 1\. Core Architecture & Philosophy\s*\n(.*?)(?=\n---\s*\n|\n## |\Z)", readme_text, re.DOTALL)
        return m.group(1).strip() if m else ""
    elif sec in ("2", "template"):
        m = re.search(r"## 2\. Standard Note Template.*?```markdown\s*\n(.*?)\n```", readme_text, re.DOTALL)
        return m.group(1).strip() if m else ""
    elif sec in ("3", "rules"):
        m = re.search(r"## 3\. Verification Rules for Authors & Agents\s*\n(.*?)(?=\n---\s*\n|\n## |\Z)", readme_text, re.DOTALL)
        return m.group(1).strip() if m else ""
    return ""


def extract_note_template(readme_text: str) -> str:
    """Extract the markdown note template block from VERIFIED-RESEARCH-README.md."""
    return extract_readme_section(readme_text, 2)


def render_template_placeholders(text: str, script_dir: Path) -> str:
    """Resolve {{path/to/template#anchor}} or {{path/to/template}} placeholders in text.

    Raises ValueError if a template file is missing or a section anchor resolves
    to empty (e.g. because the heading was renamed in the source template).
    """
    pattern = re.compile(r"\{\{([^}#]+)(?:#([^}]+))?\}\}")

    def _replace(match: re.Match) -> str:
        filepath_str = match.group(1).strip()
        anchor = match.group(2).strip() if match.group(2) else None

        # Legacy placeholder support
        if filepath_str == "NOTE_TEMPLATE":
            filepath_str = "templates/VERIFIED-RESEARCH-README.md"
            anchor = "2"

        template_path = script_dir / filepath_str
        if not template_path.exists():
            raise ValueError(
                f"Template placeholder {match.group(0)} references missing file: {template_path}"
            )

        content = template_path.read_text(encoding='utf-8')
        if anchor:
            section_content = extract_readme_section(content, anchor)
            if not section_content:
                raise ValueError(
                    f"Template placeholder {match.group(0)} resolved to empty — "
                    f"heading for section '{anchor}' may have been renamed in {template_path.name}"
                )
            return section_content
        else:
            # If no anchor and it's the verified research readme, default to section 2
            if template_path.name == "VERIFIED-RESEARCH-README.md":
                section_content = extract_readme_section(content, 2)
                if not section_content:
                    raise ValueError(
                        f"Template placeholder {match.group(0)} resolved to empty — "
                        f"heading for section '2' may have been renamed in {template_path.name}"
                    )
                return section_content
            return content

    return pattern.sub(_replace, text)



def render_verified_research_agent(agent_template_path: Path, readme_path: Path) -> str:
    """Render verified-research.md agent definition by replacing {{templates/VERIFIED-RESEARCH-README.md#...}} placeholders."""
    if not agent_template_path.exists():
        return ""
    agent_text = agent_template_path.read_text(encoding='utf-8')
    script_dir = readme_path.parent.parent
    return render_template_placeholders(agent_text, script_dir)


def sync_agents_md(agents_path: Path, template_path: Path) -> bool:
    """Ensure AGENTS.md exists and has the up-to-date managed block from template.

    Returns True if file was created or modified, False otherwise.
    """
    if not template_path.exists():
        return False

    template_content = template_path.read_text()
    managed_block = extract_managed_block(template_content)

    if not agents_path.exists():
        content = (
            "# Personal Vault Rules & Agent Instructions\n\n"
            "The following rules dictate how AI agents interact with this Obsidian workspace.\n\n"
            f"{managed_block}\n"
        )
        agents_path.write_text(content)
        return True

    existing_content = agents_path.read_text()
    if MANAGED_RE.search(existing_content):
        new_content = MANAGED_RE.sub(managed_block, existing_content)
        if new_content != existing_content:
            agents_path.write_text(new_content)
            return True
        return False
    else:
        separator = "\n\n" if not existing_content.endswith("\n\n") else ""
        if not existing_content.endswith("\n"):
            separator = "\n\n"
        new_content = f"{existing_content.rstrip()}{separator}{managed_block}\n"
        agents_path.write_text(new_content)
        return True


def scaffold_vault(
    work_dir: Path,
    script_dir: Path,
    vault_dir: Path | None = None,
    sync_agents: bool = True,
) -> dict[str, list[str]]:
    """Scaffold or update vault directories, templates, and agent rules.

    Returns a summary dict of actions taken: {'created': [...], 'updated': [...]}.
    """
    actions: dict[str, list[str]] = {'created': [], 'updated': []}

    work_dir = Path(work_dir)
    script_dir = Path(script_dir)

    # Determine vault directory
    if vault_dir is None:
        if (work_dir.parent / ".obsidian").exists() or work_dir.name in ("02-Work-Loop-Items", "Work-Loop-Items"):
            vault_dir = work_dir.parent
        elif (work_dir / ".obsidian").exists():
            vault_dir = work_dir
        else:
            vault_dir = work_dir.parent
    else:
        vault_dir = Path(vault_dir)

    templates_dir = script_dir / "templates"
    if not templates_dir.exists():
        return actions

    # 1. Standard folders
    folders_to_ensure = [
        vault_dir / "00 Inbox",
        vault_dir / "03 Verified Research",
        vault_dir / "50 Raw",
        work_dir,
    ]
    for folder in folders_to_ensure:
        if not folder.exists():
            folder.mkdir(parents=True, exist_ok=True)
            actions['created'].append(str(folder))

    # 2. WORK.md in work_dir
    work_md = work_dir / "WORK.md"
    work_template = templates_dir / "WORK.md"
    if not work_md.exists() and work_template.exists():
        shutil.copy2(work_template, work_md)
        actions['created'].append(str(work_md))

    # 3. 03 Verified Research/README.md (template is single source of truth)
    vr_readme = vault_dir / "03 Verified Research" / "README.md"
    vr_template = templates_dir / "VERIFIED-RESEARCH-README.md"
    if vr_template.exists():
        existed = vr_readme.exists()
        if not existed or vr_readme.read_text(encoding='utf-8') != vr_template.read_text(encoding='utf-8'):
            shutil.copy2(vr_template, vr_readme)
            actions['updated' if existed else 'created'].append(str(vr_readme))

    # 4. AGENTS.md in vault_dir (Marker-fenced)
    if sync_agents:
        agents_md = vault_dir / "AGENTS.md"
        agents_template = templates_dir / "vault-AGENTS.md"
        if agents_template.exists():
            existed = agents_md.exists()
            changed = sync_agents_md(agents_md, agents_template)
            if changed:
                if existed:
                    actions['updated'].append(str(agents_md))
                else:
                    actions['created'].append(str(agents_md))

    # 5. Skills in vault root (.agents/skills for Gemini, .opencode/skills, .claude/skills)
    skills_template = templates_dir / "skills"
    if skills_template.exists():
        target_skills_dirs = [
            vault_dir / ".agents" / "skills",
            vault_dir / ".opencode" / "skills",
            vault_dir / ".claude" / "skills",
        ]
        for base_skills_dir in target_skills_dirs:
            for skill_dir in skills_template.iterdir():
                if skill_dir.is_dir():
                    target_skill_dir = base_skills_dir / skill_dir.name
                    skill_file = skill_dir / "SKILL.md"
                    target_skill_file = target_skill_dir / "SKILL.md"
                    if skill_file.exists():
                        target_skill_dir.mkdir(parents=True, exist_ok=True)
                        existed = target_skill_file.exists()
                        if not existed or target_skill_file.read_text(encoding='utf-8') != skill_file.read_text(encoding='utf-8'):
                            shutil.copy2(skill_file, target_skill_file)
                            actions['updated' if existed else 'created'].append(str(target_skill_file))


    return actions


