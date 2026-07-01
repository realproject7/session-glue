---
schema_version: 1
session_id: 2026-06-30-1600-missing-head-commit
session_date: 2026-06-30
generated_at: 2026-06-30T16:00:00+09:00
project_root: /home/user/projects/example-app
repo_root: /home/user/projects/example-app
current_branch: main
agent: codex
status: in_progress
active_context_files:
  - path: src/components/PriceChart.tsx
    reason: "Main implementation target"
completed_tasks:
  - "Implemented static chart layout"
next_todo_items:
  - "Add polling lifecycle with cleanup"
known_issues:
  - "Y-axis scaling breaks when data is empty"
---

# Resume Prompt

This handoff is intentionally missing the required `head_commit` field so that
validation reports a missing-field error.
