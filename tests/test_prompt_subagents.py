#!/usr/bin/env python3
"""Tests that prompt files reference valid subagent definitions.

These tests catch the class of bug where a prompt instructs the LLM to spawn a
subagent (e.g. subagent_type="critic") but no matching agent definition file
exists in templates/agents/opencode/ or templates/agents/claude/ — causing the LLM to silently
fail to spawn the subagent at runtime.
"""

import re
import unittest
from pathlib import Path

_HERE = Path(__file__).parent.parent
_OPENCODE_AGENTS = _HERE / "templates" / "agents" / "opencode"
_CLAUDE_AGENTS = _HERE / "templates" / "agents" / "claude"

# ---------------------------------------------------------------------------
# Simple YAML frontmatter parser (no PyYAML dependency)
# ---------------------------------------------------------------------------

def _parse_frontmatter(text: str) -> dict[str, str] | None:
    """Extract simple key-value pairs from YAML frontmatter between --- delimiters.

    Handles scalar keys and one level of nested keys (e.g. 'edit: deny' under
    'permission:'). Returns None if no frontmatter found.
    """
    m = re.match(r"---\s*\n(.*?)\n---", text, re.DOTALL)
    if not m:
        return None
    raw = m.group(1)
    result: dict[str, str] = {}
    current_prefix = ""
    for line in raw.splitlines():
        if not line.strip():
            continue
        # Determine indentation level
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        indent = len(line) - len(stripped)
        if indent == 0:
            current_prefix = ""
        kv = stripped.split(":", 1)
        if len(kv) == 2:
            key = kv[0].strip()
            val = kv[1].strip()
            full_key = f"{current_prefix}.{key}" if current_prefix else key
            result[full_key] = val
            # Track current prefix for nested keys
            if indent == 0 and not val:
                current_prefix = key
            elif indent > 0 and current_prefix:
                pass  # keep prefix
    return result


def _extract_body(text: str) -> str:
    """Return the text after the YAML frontmatter closing ---."""
    m = re.match(r"---\s*\n(.*?)\n---\n?(.*)", text, re.DOTALL)
    return m.group(2) if m else text


# ---------------------------------------------------------------------------
# Discovery helpers
# ---------------------------------------------------------------------------

def _find_subagent_refs(text: str) -> list[str]:
    """Extract subagent_type="name" references from prompt text."""
    return re.findall(r'subagent_type="([^"]+)"', text)


def _load_opencode_agents() -> dict[str, Path]:
    """Return {agent_name: path} for agents in templates/agents/opencode/.

    Agent name is derived from the filename (without .md extension).
    """
    agents_dir = _OPENCODE_AGENTS
    result: dict[str, Path] = {}
    if not agents_dir.is_dir():
        return result
    for f in agents_dir.iterdir():
        if f.suffix == ".md":
            result[f.stem] = f
    return result


def _load_claude_agents() -> dict[str, Path]:
    """Return {agent_name: path} for agents in templates/agents/claude/.

    Agent name is read from the YAML frontmatter 'name' field.
    """
    agents_dir = _CLAUDE_AGENTS
    result: dict[str, Path] = {}
    if not agents_dir.is_dir():
        return result
    for f in agents_dir.iterdir():
        if f.suffix == ".md":
            fm = _parse_frontmatter(f.read_text())
            if fm and "name" in fm:
                result[fm["name"]] = f
    return result


# ---------------------------------------------------------------------------
# Prompt file discovery
# ---------------------------------------------------------------------------

_PROMPTS_DIR = _HERE / "prompts" if (_HERE / "prompts").is_dir() else _HERE

_PROMPT_FILES = [
    "LOOP-PROMPT.md",
    "IMPL-PROMPT.md",
    "RESOLVE-PROMPT.md",
    "UPDATE-RESEARCH-PROMPT.md",
    "TASK-PROMPT.md",
    "BASE-PROMPT.md",
]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSubagentReferences(unittest.TestCase):
    """Every subagent_type referenced in a prompt must have a matching agent
    definition in at least one of templates/agents/opencode/ or templates/agents/claude/."""

    @classmethod
    def setUpClass(cls):
        cls.opencode_agents = _load_opencode_agents()
        cls.claude_agents = _load_claude_agents()

    def test_prompt_files_exist(self):
        """All expected prompt files are present."""
        for name in _PROMPT_FILES:
            p = _PROMPTS_DIR / name
            self.assertTrue(p.is_file(), f"Prompt file missing: {name}")

    def test_all_subagent_refs_resolved(self):
        """Every subagent_type="X" in any prompt has a matching agent definition."""
        all_agents = {**self.opencode_agents, **self.claude_agents}

        for prompt_name in _PROMPT_FILES:
            prompt_path = _PROMPTS_DIR / prompt_name
            if not prompt_path.is_file():
                continue

            text = prompt_path.read_text()
            refs = _find_subagent_refs(text)

            for ref in refs:
                self.assertIn(
                    ref,
                    all_agents,
                    (f"{prompt_name} references subagent_type=\"{ref}\" but no "
                     f"agent definition found in templates/agents/opencode/ or templates/agents/claude/"),
                )

        for agent_name, agent_path in all_agents.items():
            text = agent_path.read_text()
            refs = _find_subagent_refs(text)
            for ref in refs:
                self.assertIn(
                    ref,
                    all_agents,
                    (f"Agent definition {agent_path.name} references subagent_type=\"{ref}\" "
                     f"but no matching agent definition found"),
                )

    def test_no_orphan_opencode_agents(self):
        """OpenCode agents that aren't referenced by any prompt are flagged."""
        all_refs: set[str] = set()
        for prompt_name in _PROMPT_FILES:
            prompt_path = _PROMPTS_DIR / prompt_name
            if not prompt_path.is_file():
                continue
            all_refs.update(_find_subagent_refs(prompt_path.read_text()))

        for agent_path in self.opencode_agents.values():
            all_refs.update(_find_subagent_refs(agent_path.read_text()))

        for agent_name in self.opencode_agents:
            self.assertIn(
                agent_name,
                all_refs,
                (f"OpenCode agent '{agent_name}' exists in templates/agents/opencode/ but "
                 f"is not referenced by any prompt file"),
            )


class TestCriticAgentDefinition(unittest.TestCase):
    """Validate the critic agent definition file structure and content."""

    def test_critic_opencode_file_exists(self):
        p = _OPENCODE_AGENTS / "critic.md"
        self.assertTrue(p.is_file(), "OpenCode critic agent file missing")

    def test_critic_claude_file_exists(self):
        p = _CLAUDE_AGENTS / "critic.md"
        self.assertTrue(p.is_file(), "Claude critic agent file missing")

    def test_critic_opencode_is_subagent(self):
        """OpenCode critic agent must have mode: subagent."""
        p = _OPENCODE_AGENTS / "critic.md"
        fm = _parse_frontmatter(p.read_text())
        self.assertIsNotNone(fm, "No YAML frontmatter in critic.md")
        self.assertEqual(fm.get("mode"), "subagent")

    def test_critic_opencode_no_edit(self):
        """OpenCode critic agent must deny edit permission."""
        p = _OPENCODE_AGENTS / "critic.md"
        fm = _parse_frontmatter(p.read_text())
        self.assertEqual(fm.get("permission.edit"), "deny")

    def test_critic_opencode_no_bash(self):
        """OpenCode critic agent must deny bash permission."""
        p = _OPENCODE_AGENTS / "critic.md"
        fm = _parse_frontmatter(p.read_text())
        self.assertEqual(fm.get("permission.bash"), "deny")

    def test_critic_has_four_checks(self):
        """Critic agent body must define all four checks."""
        p = _OPENCODE_AGENTS / "critic.md"
        body = _extract_body(p.read_text())
        for check in ("WARNING", "ASSUMPTION", "ANSWERED", "GAP"):
            self.assertIn(check, body,
                          f"Critic agent body missing check: {check}")

    def test_critic_description_in_frontmatter(self):
        """Critic agent must have a description in YAML frontmatter."""
        p = _OPENCODE_AGENTS / "critic.md"
        fm = _parse_frontmatter(p.read_text())
        self.assertIn("description", fm)
        self.assertTrue(len(fm["description"]) > 10,
                        "Description too short")

    def test_critic_no_file_writes_instruction(self):
        """Critic agent must instruct NOT to write files."""
        p = _OPENCODE_AGENTS / "critic.md"
        text = p.read_text()
        self.assertRegex(text, r"(?i)do\s+not\s+.*write.*file",
                         "Critic should explicitly forbid file writes")


class TestCriticPromptIntegration(unittest.TestCase):
    """Verify LOOP-PROMPT.md correctly invokes the critic subagent."""

    def test_loop_prompt_spawns_critic(self):
        prompt = (_PROMPTS_DIR / "LOOP-PROMPT.md").read_text()
        self.assertIn('subagent_type="critic"', prompt,
                       "LOOP-PROMPT must spawn critic subagent")

    def test_loop_prompt_passes_item_dir(self):
        """Critic spawn instruction must include ITEM_DIR."""
        prompt = (_PROMPTS_DIR / "LOOP-PROMPT.md").read_text()
        # The spawn block should reference ITEM_DIR
        self.assertIn("ITEM_DIR", prompt,
                       "LOOP-PROMPT must pass ITEM_DIR to subagent")

    def test_loop_prompt_passes_draft(self):
        """Critic spawn instruction must include the DRAFT content."""
        prompt = (_PROMPTS_DIR / "LOOP-PROMPT.md").read_text()
        self.assertIn("DRAFT", prompt,
                       "LOOP-PROMPT must pass DRAFT to critic")

    def test_loop_prompt_step3_references_critic_output(self):
        """Step 3 must tell the agent to read Critic output."""
        prompt = (_PROMPTS_DIR / "LOOP-PROMPT.md").read_text()
        m = re.search(r"## Step 3\s+—", prompt, re.IGNORECASE)
        self.assertIsNotNone(m, "Prompt must have a Step 3 section")
        # Extract text from Step 3 to next ## header
        rest = prompt[m.end():]
        next_section = re.search(r"\n## ", rest)
        step3_text = rest[:next_section.start()] if next_section else rest
        self.assertRegex(step3_text, r"(?i)critic",
                         "Step 3 must reference Critic output")


class TestCodeReviewerAgentDefinition(unittest.TestCase):
    """Validate the code-reviewer agent definition."""

    def test_code_reviewer_opencode_exists(self):
        p = _OPENCODE_AGENTS / "code-reviewer.md"
        self.assertTrue(p.is_file(), "OpenCode code-reviewer agent file missing")

    def test_code_reviewer_claude_exists(self):
        p = _CLAUDE_AGENTS / "code-reviewer.md"
        self.assertTrue(p.is_file(), "Claude code-reviewer agent file missing")

    def test_code_reviewer_opencode_is_subagent(self):
        p = _OPENCODE_AGENTS / "code-reviewer.md"
        fm = _parse_frontmatter(p.read_text())
        self.assertEqual(fm.get("mode"), "subagent")

    def test_code_reviewer_opencode_has_bash(self):
        """Code-reviewer needs bash to run tests."""
        p = _OPENCODE_AGENTS / "code-reviewer.md"
        fm = _parse_frontmatter(p.read_text())
        self.assertEqual(fm.get("permission.bash"), "allow")

    def test_impl_prompt_spawns_code_reviewer(self):
        prompt = (_PROMPTS_DIR / "IMPL-PROMPT.md").read_text()
        self.assertIn('subagent_type="code-reviewer"', prompt,
                       "IMPL-PROMPT must spawn code-reviewer subagent")


class TestResearchWorkerAgentDefinition(unittest.TestCase):
    """Validate the research-worker leaf agent definition."""

    def test_research_worker_opencode_exists(self):
        p = _OPENCODE_AGENTS / "research-worker.md"
        self.assertTrue(p.is_file(), "OpenCode research-worker agent file missing")

    def test_research_worker_claude_exists(self):
        p = _CLAUDE_AGENTS / "research-worker.md"
        self.assertTrue(p.is_file(), "Claude research-worker agent file missing")

    def test_research_worker_opencode_is_subagent(self):
        p = _OPENCODE_AGENTS / "research-worker.md"
        fm = _parse_frontmatter(p.read_text())
        self.assertIsNotNone(fm, "No YAML frontmatter in research-worker.md")
        self.assertEqual(fm.get("mode"), "subagent")

    def test_research_worker_opencode_permissions(self):
        p = _OPENCODE_AGENTS / "research-worker.md"
        fm = _parse_frontmatter(p.read_text())
        self.assertEqual(fm.get("permission.edit"), "deny")
        self.assertEqual(fm.get("permission.bash"), "deny")
        self.assertEqual(fm.get("permission.write"), "allow")
        self.assertEqual(fm.get("permission.read"), "allow")

    def test_research_worker_claude_permissions(self):
        p = _CLAUDE_AGENTS / "research-worker.md"
        fm = _parse_frontmatter(p.read_text())
        self.assertEqual(fm.get("permission.edit"), "deny")
        self.assertEqual(fm.get("permission.bash"), "deny")
        self.assertEqual(fm.get("permission.write"), "allow")
        self.assertEqual(fm.get("permission.read"), "allow")

    def test_research_worker_description_in_frontmatter(self):
        p = _OPENCODE_AGENTS / "research-worker.md"
        fm = _parse_frontmatter(p.read_text())
        self.assertIn("description", fm)
        self.assertTrue(len(fm["description"]) > 15, "Description too short")

    def test_research_worker_one_line_return_instruction(self):
        p = _OPENCODE_AGENTS / "research-worker.md"
        text = p.read_text()
        self.assertIn("Done: Raw research written to", text)
        self.assertRegex(text, r"(?i)return\s+.*only", "Worker must instruct minimal return")

    def test_research_worker_context_protection(self):
        p = _OPENCODE_AGENTS / "research-worker.md"
        text = p.read_text()
        self.assertIn("Context Window Protection", text)

    def test_research_worker_has_vault_and_web_scopes(self):
        text = (_OPENCODE_AGENTS / "research-worker.md").read_text()
        self.assertIn("## Scope: vault", text)
        self.assertIn("## Scope: web", text)
        self.assertIn("03 Verified Research/", text)
        self.assertIn("50 Raw/", text)

    def test_research_worker_includes_verification_rules(self):
        text = (_OPENCODE_AGENTS / "research-worker.md").read_text()
        self.assertIn("{{templates/VERIFIED-RESEARCH-README.md#3}}", text)


class TestVerifiedResearchAgentDefinition(unittest.TestCase):
    """Validate the verified-research orchestrator agent definition."""

    def test_verified_research_opencode_exists(self):
        p = _OPENCODE_AGENTS / "verified-research.md"
        self.assertTrue(p.is_file(), "OpenCode verified-research agent file missing")

    def test_verified_research_claude_exists(self):
        p = _CLAUDE_AGENTS / "verified-research.md"
        self.assertTrue(p.is_file(), "Claude verified-research agent file missing")

    def test_verified_research_opencode_is_subagent(self):
        p = _OPENCODE_AGENTS / "verified-research.md"
        fm = _parse_frontmatter(p.read_text())
        self.assertEqual(fm.get("mode"), "subagent")

    def test_verified_research_permissions(self):
        for agents_dir in (_OPENCODE_AGENTS, _CLAUDE_AGENTS):
            p = agents_dir / "verified-research.md"
            fm = _parse_frontmatter(p.read_text())
            self.assertEqual(fm.get("permission.edit"), "deny")
            self.assertEqual(fm.get("permission.bash"), "deny")
            self.assertEqual(fm.get("permission.write"), "allow")
            self.assertEqual(fm.get("permission.read"), "allow")

    def test_verified_research_has_dynamic_anchors(self):
        p = _OPENCODE_AGENTS / "verified-research.md"
        text = p.read_text()
        self.assertIn("{{templates/VERIFIED-RESEARCH-README.md#1}}", text)
        self.assertIn("{{templates/VERIFIED-RESEARCH-README.md#2}}", text)
        self.assertIn("{{templates/VERIFIED-RESEARCH-README.md#3}}", text)

    def test_verified_research_spawns_research_worker(self):
        p = _OPENCODE_AGENTS / "verified-research.md"
        text = p.read_text()
        self.assertIn('subagent_type="research-worker"', text)

    def test_verified_research_supports_three_modes(self):
        p = _OPENCODE_AGENTS / "verified-research.md"
        text = p.read_text()
        for mode in ("`research`", "`synthesize`", "`refresh`"):
            self.assertIn(mode, text)
        # Legacy mode names from callers still in the wild must keep working
        self.assertIn("`de_novo`", text)
        self.assertIn("`discussion_synthesis`", text)

    def test_verified_research_scans_vault_before_web(self):
        text = (_OPENCODE_AGENTS / "verified-research.md").read_text()
        vault = text.index("scope: vault")
        web = text.index("scope: web")
        self.assertLess(vault, web, "Vault scan must be dispatched before web workers")

    def test_verified_research_never_writes_03_directly_in_work_loop(self):
        text = (_OPENCODE_AGENTS / "verified-research.md").read_text()
        self.assertIn("draft-{topic-slug}.md", text)
        self.assertIn("never write into `03 Verified Research/` yourself", text)

    def test_research_agents_claude_and_opencode_in_sync(self):
        """The .opencode copies equal the .claude ones minus the model line and the sync-path comment."""
        for name in ("verified-research", "research-worker"):
            claude = (_CLAUDE_AGENTS / f"{name}.md").read_text()
            expected = "".join(
                line for line in claude.splitlines(keepends=True) if not line.startswith("model: ")
            ).replace("(.claude/agents/)", "(.opencode/agents/)")
            actual = (_OPENCODE_AGENTS / f"{name}.md").read_text()
            self.assertEqual(actual, expected, f"{name}: .opencode copy drifted from .claude")

    def test_loop_prompt_spawns_verified_research(self):
        prompt = (_PROMPTS_DIR / "LOOP-PROMPT.md").read_text()
        self.assertIn('subagent_type="verified-research"', prompt)

    def test_loop_prompt_offers_modes_and_promotes_drafts(self):
        prompt = (_PROMPTS_DIR / "LOOP-PROMPT.md").read_text()
        step7 = prompt[prompt.index("## Step 7"):]
        for mode in ("`research`", "`synthesize`", "`refresh`"):
            self.assertIn(mode, step7)
        self.assertIn("**Promotion (on approval):**", step7)
        # Without this, models follow the "analyze and ask" ground rule and ask before running it
        self.assertIn("**Do not ask for confirmation first.**", step7)
        self.assertIn("Exception: when the user explicitly asks for verified research", prompt)

    def test_skills_use_current_modes(self):
        skills = _HERE / "templates" / "skills"
        expected = {
            "verified-research": "`research`",
            "synthesize-research": "`synthesize`",
            "refresh-research": "`refresh`",
        }
        for name, mode in expected.items():
            text = (skills / name / "SKILL.md").read_text()
            self.assertIn(f"name: {name}", text)
            self.assertIn(f"`mode`: {mode}", text)

    def test_vault_agents_template_spawns_verified_research(self):
        prompt = (_HERE / "templates" / "vault-AGENTS.md").read_text()
        self.assertIn('subagent_type="verified-research"', prompt)

    def test_verified_research_context_protection(self):
        p = _OPENCODE_AGENTS / "verified-research.md"
        text = p.read_text()
        self.assertIn("Context Window Protection", text)

    def test_verified_research_one_line_return_instruction(self):
        p = _OPENCODE_AGENTS / "verified-research.md"
        text = p.read_text()
        self.assertIn("Done: Verified research note written to", text)


if __name__ == "__main__":
    unittest.main()

