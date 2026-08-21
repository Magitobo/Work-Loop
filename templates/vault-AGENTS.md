# Personal Vault Rules & Agent Instructions

The following rules dictate how AI agents interact with this Obsidian workspace.

<!-- WORK-LOOP:START — DO NOT EDIT THIS BLOCK MANUALLY -->
## 1. Verified Research Rules
- **Verified Research Notes**: When creating, updating, or synthesizing notes in `03 Verified Research/`, the agent must first read and strictly adhere to the guidelines and template defined in `03 Verified Research/README.md`.
- **Source Grounding**: Claims must be extracted with verbatim quotes, confidence ratings, and linked to raw sources in `50 Raw/` or live URLs.

## 2. Obsidian Native CLI Operations & Efficiency
- **Binary Path**: The official Obsidian CLI binary on macOS is located at `/Applications/Obsidian.app/Contents/MacOS/Obsidian`.
- **Active Note Retrieval**: When the user references "the active file", "this note", "what is on my screen", or "current file", the agent must run `/Applications/Obsidian.app/Contents/MacOS/Obsidian read` to fetch real-time editor content (including unsaved edits).
- **Move / Rename (Link Integrity)**: Always use `obsidian move path="Old/Path.md" to="New/Path.md"` or `obsidian rename` instead of filesystem `mv`. This instructs Obsidian to automatically rewrite and update all internal wikilinks across the vault.
  - Paths must be vault-relative and include `.md`.
  - Commands are silent on success; verify with filesystem check.
- **Read & Search Performance**: For static file reading, multi-file inspection, or searching, use direct filesystem tools (`view_file`, `grep_search`, `find_by_name`) to avoid CLI IPC overhead.
- **Runtime Introspection (`eval`)**: Use `obsidian eval code="..."` to query live Obsidian workspace state or plugin APIs when needed.
<!-- WORK-LOOP:END -->
