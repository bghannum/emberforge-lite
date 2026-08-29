# Security

Emberforge Lite is a **single-user, local-first** tool. It binds only to
loopback (`127.0.0.1`) and is not designed to be exposed to a network or run as
a shared service. See [docs/threat-model.md](docs/threat-model.md) for the full
model and the boundaries it does and does not defend.

## What the local server protects

- Binds to `127.0.0.1` only, and rejects requests whose `Host` header is not a
  loopback name (a DNS-rebinding defense).
- Serves only generated pages, packaged static assets, and actor media.
  Credentials, Git metadata, Python source, prompts, and the spend ledger
  return `404`.
- Requires a same-origin `Origin` and a per-process CSRF token on every
  state-changing request.
- Sends `Content-Security-Policy` (no `unsafe-inline`), `X-Content-Type-Options`,
  `X-Frame-Options: DENY`, a strict referrer policy, and `Cache-Control: no-store`.
- Validates uploads before committing them and writes through atomic temp files.

## Credentials

Provider API keys are read from the process environment, or from a file you pass
explicitly with `--env-file`. Emberforge Lite never searches the repository or
working directory for a `.env`, never logs key values, and never writes them to
disk. Without `--allow-spend` the app runs deterministic offline fakes and
cannot reach any provider.

## Reporting a vulnerability

Please report suspected vulnerabilities privately through GitHub's
[private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
on this repository, rather than opening a public issue. Include the version, a
description of the class of problem, and the minimal steps to reproduce it.
Please do not include working exploit code in the initial report.
