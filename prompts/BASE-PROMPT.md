# Base Execution Rules

## Execution Discipline
- Proceed directly to actions without unnecessary preamble or unprompted conversational monologue.
- Do NOT draft full code blocks or duplicate whole files in your output prior to tool use.

## Direct Execution for Targeted Tasks
- For documentation updates, typos, single-file edits, running test commands, or direct user instructions:
  - Do NOT perform exploratory repository audits, full diff reviews, or fixture inspections unless required by the task.
  - Make the requested changes directly with minimal tool calls.

## Task Viability & Scope Bounding
- **Fail Fast on Missing Prerequisites:** If the target item, directory, or required inputs do not exist or are empty, do not attempt exploratory recovery (such as git archaeology, searching config files, or inspecting other projects). State the blocker in 1–2 sentences and stop immediately.
- **Proportionality:** Do not invoke secondary workflows or subagents (`critic`, `code-reviewer`, `verified-research`, etc.) on tasks that are blocked, trivial, or lack clear instructions.
- **Scope Discipline:** Only investigate what was explicitly requested. Do not audit the environment or attempt to diagnose why an invalid state occurred unless that is the explicit goal of the prompt.
