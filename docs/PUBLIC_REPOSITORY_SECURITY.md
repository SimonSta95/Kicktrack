# Public repository security checklist

The repository is public, but public visibility does **not** grant write access. Only explicitly added collaborators and authorized GitHub Apps can push. The controls below reduce the risk from compromised accounts, accidental secret commits, dependency vulnerabilities, and untrusted pull requests.

## GitHub settings

Configure these controls in the repository settings:

### Security and analysis

- Enable the dependency graph.
- Enable Dependabot alerts and Dependabot security updates.
- Enable secret scanning.
- Enable push protection for secrets, including generic secrets if offered.
- Enable CodeQL default setup for JavaScript/TypeScript and Rust.
- Enable private vulnerability reporting.

### Actions / General

- Keep workflow permissions at **Read repository contents and packages permissions**.
- Do not allow GitHub Actions to create or approve pull requests unless a future release workflow explicitly needs it.
- Require approval for workflows from all outside collaborators, or at minimum all first-time contributors.
- Allow only actions required by the checked-in workflows. Review changes under `.github/workflows/` before approving a fork workflow.

### Rules / Rulesets

Create an active branch ruleset targeting the default branch:

- block force pushes;
- block branch deletion;
- require the `verify` CI job before merge;
- require conversation resolution before merge;
- require pull requests if anyone besides the owner receives write access.

For a single-maintainer repository, requiring a pull request for every owner change is optional. It improves auditability but adds friction. Force-push and deletion protection should still remain enabled.

### Access and features

- Review collaborators and installed GitHub Apps; remove anything that does not need write access.
- Disable Wiki and Discussions when they are not used to reduce moderation and spam surfaces.
- Keep issue templates free of prompts for logs containing tokens or private league data.

## Incident response

If a password, Kickbase token, session cookie, GitHub token, signing key, or private league export is ever pushed:

1. revoke or rotate it immediately;
2. remove it from the current tree;
3. rewrite affected Git history when necessary;
4. review forks, Actions logs, release artifacts, and GitHub security alerts;
5. do not assume that deleting the latest commit invalidates a copied credential.
