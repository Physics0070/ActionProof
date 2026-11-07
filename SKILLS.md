# SKILLS

Library inventoried 2026-11-07 (installed skills + plugin skills; several appear twice, plain and `anthropic-skills:` prefixed — same content). Only skills relevant to ActionProof are mapped. Every phase also uses: karpathy-guidelines, ponytail (ultra), verification-before-completion.
All 60+ skills named in the brief exist in the library; none needed `npx skills find` so far.

| Phase | Mapped skills | Used so far |
|---|---|---|
| 1 Foundation | planning-and-task-breakdown, writing-plans, spec-driven-development, contract-first, documentation-and-adrs, architecture-decision-records, living-docs-governance, agent-development, subagent-driven-development, docker-patterns | yes (all but subagent-driven-development, docker-patterns loaded) |
| 2 Claims | python-patterns, python-testing, test-driven-development, tdd-workflow, security-review, error-handling | TDD enforced via subagent briefs (tests first); subagent-driven-development used (Opus 5.5 hard tasks, Haiku 5.5 mechanical) |
| 3 Gate | postgres-patterns, database-migrations, security-and-hardening, cso, auth, fastapi-patterns, api-design, error-handling, ai-regression-testing | red-team round via gate-reviewer role (Opus 5.5); regression tests kept in tests/redteam |
| 4 Decisions | llm-council | – |
| 5 Surface | mcp-builder, mcp-server-patterns, fastapi-patterns, api-design, agent-development, agent-eval, security-review | – |
| 6 Proof | eval-harness, benchmark-methodology, agent-eval, ai-regression-testing, subagent-driven-development | – |
| 7 UI | design-manual, awwwards, react-three-fiber, motion-patterns, frontend-design, frontend-a11y, 21st-ui, nextjs-turbopack, react-performance, auth | – |
| 8 Ship | e2e-testing, webapp-testing, browser-qa, jury, docker-patterns, ci-cd-and-automation, deployment-patterns, video-editing, documentation-and-adrs | – |

Installed from outside the library: none.
