# AI Stance — uFawkesDORA

> Last reviewed: 2026-06-24
> Next review due: 2026-09-22 (quarterly)
> Owner: paruff
> Suite: uFawkesAI

## Expectation of Use

AI-assisted development is expected in this repo. We use AI tools to clear bottlenecks in the product lifecycle — not to replace human judgment on architecture, security, and user research decisions. All AI assistance is logged via opencode session history.

## Organizational Support

- Permitted tools: listed below
- Skill suite: uFawkesAI `.agents/skills/` — load relevant skills before each session
- Context corpus: maintained via context-engineering skill (load at session start)
- Questions or policy concerns: file a GitHub issue with label `ai-policy`
- Policy reviews: quarterly — see ai-policy-lifecycle skill

## Permitted Tools

| Tool           | Model / version   | Scope                                               |
| -------------- | ----------------- | --------------------------------------------------- |
| opencode       | latest stable     | Primary agentic development tool                    |
| Claude         | claude-sonnet-4-6 | Skill authoring, code review, content generation    |
| graphify       | community         | Context corpus building — verify variant before use |
| ponytail       | latest stable     | YAGNI enforcement in all agent sessions             |
| GitHub Copilot | current           | IDE code completion                                 |

## Three-Bucket Classification

### Prohibited

- Sending PII, credentials, or proprietary infrastructure configs to public AI models
- Committing AI-generated code without pre-commit hooks passing
- Bypassing branch protection rules on AI guidance
- AI-generated security policy or compliance docs without qualified human review
- AI-generated SQL migrations or hypertables without manual database administrator review (schema changes are highly critical in production hypertables)

### Permitted with Guardrails

| Use                                     | Guardrail                                                    |
| --------------------------------------- | ------------------------------------------------------------ |
| AI-generated code merged to main        | Human review required; at least one test covering the change |
| AI-assisted spec / design documents     | discovery-brief.md must exist first                          |
| Agent sessions modifying infrastructure | j-curve-navigation pre-flight check must pass                |
| AI-generated release notes              | Human review before publishing                               |
| AI-generated content in Dojo modules    | Disclose to learners that AI assisted in authoring           |
| opencode sessions in this repo          | Load AGENTS.md and relevant skills at session start          |
| graphify corpus built from this repo    | Corpus must not include files containing secrets or PII      |

### Allowed

- AI-assisted code completion for any file not in the Prohibited scope
- AI-generated first drafts of blog posts, dev.to articles, LinkedIn posts
- AI-assisted GitHub issue triage and labeling
- AI-generated test stubs (human completes and verifies)
- Asking AI tools to explain existing code or documentation

## Role Applicability

This stance applies to: **human contributors AND AI agents** (opencode sessions, GitHub Actions opencode workflow, any automated agent invocation in this repo).

Agents must:

1. Load `ai-stance` skill and verify this document exists before beginning work
2. Log the session via opencode session history
3. Flag any action that would fall into the Prohibited bucket and halt — do not proceed without explicit human authorization for prohibited actions
