# Security Policy

## Reporting a vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

If you discover a security issue in this codebase, please report it privately:

1. Go to **Security → Report a vulnerability** on this repository (GitHub Private Security Advisories)
2. Or email the maintainer directly (contact via GitHub profile)

We will acknowledge your report within **48 hours** and aim to release a patch within **7 days** for critical issues.

## What counts as a security vulnerability

- Authentication or authorization bypass
- SQL injection or RLS bypass (cross-tenant data access)
- JWT token forgery or replay
- OTP flow manipulation (rate limit bypass, code reuse)
- Remote code execution
- Sensitive data exposure in logs or API responses
- Server-Side Request Forgery (SSRF)

## What does not need private disclosure

- Bugs in non-security-sensitive features (use a regular issue)
- Performance issues
- Feature requests

## Supported versions

Only the latest commit on `main` is actively supported. There are no versioned releases at this time.
