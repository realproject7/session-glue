# Security Policy

## Reporting A Vulnerability

Please report security issues privately to the repository owner instead of opening a public issue.

Do not include live credentials in reports. Redact tokens, cookies, keys, and customer data.

## Handoff Data Warning

Session Glue writes local handoff files that may describe implementation details. Projects should decide whether `.agent-history/` belongs in git.

The default repository `.gitignore` excludes `.agent-history/` so handoffs stay local unless a project intentionally changes that policy.
