---
schema_version: 1
session_id: 2026-06-30-1600-missing-head-commit
session_date: 2026-06-30
generated_at: 2026-06-30T16:00:00+09:00
project_root: /path/to/project
repo_root: /path/to/project
current_branch: main
agent: codex
status: in_progress
primary_goal: Ship the chart polling lifecycle with clean teardown
active_context_files:
  - path: src/components/ChartView.tsx
    reason: "Main implementation target"
completed_tasks:
  - "Implemented static chart layout"
next_todo_items:
  - "Add polling lifecycle with cleanup"
known_issues:
  - "Y-axis scaling breaks when data is empty"
search_tags:
  - charts
  - polling
validation:
  - command: npm test
    result: passed
    notes: "Unit suite green"
---

# Resume Prompt

This handoff is intentionally missing the required `head_commit` field so that
validation reports a missing-field error.
