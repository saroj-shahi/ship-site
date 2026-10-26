# Security policy

## Supported versions

Only the latest release gets security fixes.

## Reporting a vulnerability

Please report vulnerabilities privately, not in a public issue. Use **Report a vulnerability** on the [Security tab](https://github.com/saroj-shahi/ship-site/security/advisories/new). You can expect a first response within 7 days.

Relevant reports include:

- the scripts sending headers or credentials anywhere other than the site under test (for example `smoke_test.py --header` leaking to a third-party host or over plain http)
- the scripts reading or writing outside the paths they are given
- skill instructions that lead Claude to push, publish, submit forms, or commit secrets without the stop-and-ask checkpoint described in the README

## Scope

ship-site runs inside Claude Code with your permissions, against repositories and sites you point it at. Problems in Claude Code itself go to [Anthropic](https://www.anthropic.com/responsible-disclosure-policy), and problems in a site that ship-site audits go to that site's owner.
