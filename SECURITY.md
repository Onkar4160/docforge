# Security

This document describes security-related behavior visible in the current source. It is not a security certification or a guarantee that every deployment is safe.

## Reporting a vulnerability

No security contact or private reporting policy is configured in the repository. If GitHub private vulnerability reporting is enabled for the upstream repository, use that channel. Otherwise, contact the repository maintainer privately through an official contact channel and request a secure reporting route before sharing technical details. Do not post credentials, private user data, or an actionable vulnerability report in a public issue. The repository owner should publish a monitored security contact and response process.

## Secrets and configuration

- `.env` is ignored by Git; `.env.example` contains sample values. Keep actual API keys and JWT secrets out of commits, logs, screenshots, and generated artifacts.
- The default login (`demo` / `demo123`) and `JWT_SECRET=change-me-to-a-random-secret` are development defaults, not production credentials.
- With `APP_ENV=prod` and authentication enabled, startup rejects the default JWT secret. This does not enforce a changed demo password or establish a full production security posture.
- Store secrets in a protected environment or secret manager; rotate credentials if exposed.
- `docforge health` reports a subset of configuration but should not be treated as a credential validity check.

## Authentication and authorization

The current API uses a signed bearer JWT. `POST /api/auth/login` compares one configured username/password; other `/api/*` endpoints require bearer authentication unless `AUTH_ENABLED=false`. Session and artifact access is scoped to the configured owner, and foreign sessions are returned as not found. `/health` and the static UI entry are public.

The code currently supports one configured login, not multi-user account management, password reset, or a user database. Do not disable auth for a reachable or shared service. Use TLS through a trusted reverse proxy for network access.

## File and content handling

The upload path enforces a configured size limit and inspects file content/type; template uploads are restricted to office template-capable types. The repository guidance also specifies untrusted-file handling, macro rejection, and XML/zip protections; see `src/docforge/core/files.py` and the implementation in `src/docforge/ingest/`. Continue treating uploaded files, extracted text, and fetched web content as untrusted data.

Uploaded files, generated artifacts, the database, and optional LLM cassettes can contain user or business information. Protect `STORAGE_DIR`, backups, logs, and any cassette directory with appropriate access controls and retention practices. Cassette recording may persist prompts/provider replies; leave it off unless needed and protect recorded data.

## Network and external services

LLM, search, embedding, vector, and image integrations may send request data to the configured service. Review each provider's data handling terms before enabling it for sensitive content. Use trusted endpoints for OpenAI-compatible providers. Research URLs and user-supplied data should not be assumed trustworthy.

## Dependency and deployment hygiene

- Review dependency updates declared in `pyproject.toml`; install from a trusted package source and run tests after upgrades.
- No Docker image, deployment hardening profile, rate limiter, or automated vulnerability scanning workflow was found in the repository.
- The API uses a development server command for local execution. Do not expose an unreviewed development deployment directly to the internet.
- Keep Python and dependencies patched, bind to a private interface behind TLS, restrict network access, and back up data securely.

## Limitations

Security controls can change with implementation. Re-check authentication dependencies, file validation, storage access, provider data flows, and deployment settings in the current code before handling sensitive information.