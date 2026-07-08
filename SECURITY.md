# Security Policy

## Reporting A Vulnerability

Please report security issues privately to the repository owner instead of opening a public issue.

Do not include live credentials in reports. Redact tokens, cookies, keys, and customer data.

## Handoff Data Warning

Session Glue writes local handoff files that may describe implementation details. Projects should decide whether `.agent-history/` belongs in git.

The default repository `.gitignore` excludes `.agent-history/` so handoffs stay local unless a project intentionally changes that policy.

## Symlink Guards And The TOCTOU Window

Session Glue refuses to follow symlinks that would redirect its writes outside the
repository. These guards are *check-then-write*: the CLI validates a path and then
writes to it as separate steps, so a time-of-check/time-of-use (TOCTOU) window exists
in which a local attacker could swap a checked path for a symlink between the two
steps.

We accept this residual window because Session Glue's threat model is local and
single-user. The CLI runs on your machine, on repositories you already control, with
your own filesystem privileges — an attacker able to win that race already has local
write access to your working tree and does not need Session Glue to do damage. Session
Glue is not a sandbox or a privilege boundary; it does not defend against a local
adversary who can modify files under the repository concurrently.
