# Personal Vault Rules & Agent Instructions

The following rules dictate how AI agents interact with this Obsidian workspace.

<!-- WORK-LOOP:START — DO NOT EDIT THIS BLOCK MANUALLY -->
## 1. Verified Research Rules
- **Verified Research Notes**: When creating, updating, or synthesizing notes in `03 Verified Research/`, adhere strictly to the guidelines defined in `03 Verified Research/README.md`.
- **Primary Thread Context Protection**: In both interactive sessions and work-loop turns, the main agent must **NEVER** fetch raw web pages or read full multi-KB reference notes into the primary conversation context. Note creation must be delegated to `subagent_type="verified-research"`.
- **Retrospective Synthesis (Path B)**: When compiling a note from an existing conversation, use the quotes and URLs already established in the dialogue. Do not re-fetch cited web pages into the primary session context.
- **Reference Reading Limits**: When checking formatting against existing notes, read only the template in `README.md` or the first 30–50 lines of an existing note (`limit=50`), never reading entire large files into memory.

## 2. Obsidian Native CLI Operations & Efficiency
- **Binary Path**: The official Obsidian CLI binary on macOS is located at `/Applications/Obsidian.app/Contents/MacOS/Obsidian`.
- **Active Note Retrieval**: When the user references "the active file", "this note", "what is on my screen", or "current file", the agent must run `/Applications/Obsidian.app/Contents/MacOS/Obsidian read` to fetch real-time editor content (including unsaved edits).
- **Move / Rename (Link Integrity)**: Always use `obsidian move path="Old/Path.md" to="New/Path.md"` or `obsidian rename` instead of filesystem `mv`. This instructs Obsidian to automatically rewrite and update all internal wikilinks across the vault.
  - Paths must be vault-relative and include `.md`.
  - Commands are silent on success; verify with filesystem check.
- **Read & Search Performance**: For static file reading, multi-file inspection, or searching, use direct filesystem tools (`view_file`, `grep_search`, `find_by_name`) to avoid CLI IPC overhead.
- **Runtime Introspection (`eval`)**: Use `obsidian eval code="..."` to query live Obsidian workspace state or plugin APIs when needed.
<!-- WORK-LOOP:END -->
