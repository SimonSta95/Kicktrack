# Security Policy

## Supported versions

Security fixes are provided for the latest published KickTrack release. Older portable builds should be updated before reporting a problem that may already be fixed.

## Reporting a vulnerability

Please do not open a public issue for vulnerabilities, leaked credentials, authentication problems, or reports that contain private Kickbase data.

Use GitHub's **Private vulnerability reporting** feature in the repository's **Security** tab. Include:

- the affected KickTrack version;
- steps to reproduce the issue;
- the expected and observed behavior;
- the potential impact;
- sanitized logs or screenshots, without passwords, access tokens, session cookies, or private league data.

If private vulnerability reporting is temporarily unavailable, open a public issue containing only a request for a private contact channel. Do not include vulnerability details in that issue.

## Credential safety

KickTrack credentials and session tokens must never be committed, attached to issues, or included in logs. If a credential is exposed, revoke or rotate it immediately; removing it from the latest commit is not sufficient because Git history and forks may retain it.
