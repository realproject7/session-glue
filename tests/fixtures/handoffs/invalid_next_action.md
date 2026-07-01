---
schema_version: 1
session_id: 2026-06-30-1630-resume-mechanic-first
session_date: 2026-06-30
generated_at: 2026-06-30T16:30:00+09:00
project_root: /path/to/project
repo_root: /path/to/project
current_branch: main
head_commit: abc1234
agent: codex
status: in_progress
active_context_files:
  - path: src/components/ChartView.tsx
    reason: "Main implementation target"
completed_tasks:
  - "Implemented static chart layout"
next_todo_items:
  - "Start a new session and paste RESUME_PROMPT.txt"
  - "Add polling lifecycle with cleanup"
known_issues:
  - "Y-axis scaling breaks when data is empty"
---

# Resume Prompt

This handoff is intentionally invalid: `next_todo_items[0]` is a resume mechanic
rather than the first productive work item, so the lint must flag it.
