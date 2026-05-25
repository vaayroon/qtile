# Skill Registry — vaayroon-qtile

> Generated: 2026-05-25 | Source: `~/.copilot/skills/`

## User Skills

### branch-pr
**Trigger**: creating, opening, or preparing PRs for review  
**Path**: `~/.copilot/skills/branch-pr/SKILL.md`  
**Compact Rules**:
- Every PR MUST link an approved issue — no exceptions
- Every PR MUST have exactly one `type:*` label
- Automated checks must pass before merge
- Blank PRs without issue linkage are blocked

---

### chained-pr
**Trigger**: PRs over 400 lines, stacked PRs, review slices  
**Path**: `~/.copilot/skills/chained-pr/SKILL.md`  
**Compact Rules**:
- Split any PR over 400 changed lines (unless `size:exception`)
- Each PR must be reviewable in ≤60 minutes
- One deliverable work unit per PR; tests/docs with the unit they verify
- Every child PR includes a dependency diagram marking current PR with 📍
- Feature Branch Chain: create draft tracker PR; child #1 targets tracker branch

---

### cognitive-doc-design
**Trigger**: writing guides, READMEs, RFCs, onboarding, architecture, or review-facing docs  
**Path**: `~/.copilot/skills/cognitive-doc-design/SKILL.md`  
**Compact Rules**:
- Lead with the decision/action/outcome first; context after
- Progressive disclosure: happy path → details → edge cases
- Group related info in small sections; keep flat lists short
- Use headings, labels, callouts so readers know where they are
- Prefer tables, checklists, templates over prose that must be remembered

---

### comment-writer
**Trigger**: PR feedback, issue replies, reviews, Slack messages, or GitHub comments  
**Path**: `~/.copilot/skills/comment-writer/SKILL.md`  
**Compact Rules**:
- Start with the actionable point; do not recap the whole PR first
- Sound like a thoughtful teammate, not a corporate bot
- 1-3 short paragraphs or tight bullet list
- Always give the technical reason when requesting a change
- Spanish threads: use Rioplatense voseo (`podés`, `tenés`, `fijate`)

---

### go-testing
**Trigger**: Go tests, go test coverage, Bubbletea teatest, golden files  
**Path**: `~/.copilot/skills/go-testing/SKILL.md`  
**Compact Rules**:
- Table-driven tests for multiple cases; use `t.Run(tt.name, ...)`
- Test behavior and state transitions, not implementation trivia
- `t.TempDir()` for filesystem tests; never rely on real home directory
- Integration tests skippable with `testing.Short()`
- Golden files must be deterministic; update only via `-update` flag
- N/A for this Python project but available for cross-language work

---

### issue-creation
**Trigger**: creating GitHub issues, bug reports, or feature requests  
**Path**: `~/.copilot/skills/issue-creation/SKILL.md`  
**Compact Rules**:
- MUST use a template (bug report or feature request)
- Every issue gets `status:needs-review` on creation
- A maintainer MUST add `status:approved` before any PR can open
- Questions go to Discussions, not Issues

---

### judgment-day
**Trigger**: judgment day, dual review, adversarial review, juzgar  
**Path**: `~/.copilot/skills/judgment-day/SKILL.md`  
**Compact Rules**:
- Read skill registry and inject `Project Standards` into both judge prompts
- Launch two blind judges in parallel; never review code yourself
- Wait for both judges before synthesis
- Classify `WARNING (real)` only if normal usage can trigger it
- Ask before fixing Round 1 confirmed issues
- Re-launch both judges after every fix batch, before done/session summary
- Terminal states: `JUDGMENT: APPROVED` or `JUDGMENT: ESCALATED` only

---

### skill-creator
**Trigger**: new skills, agent instructions, documenting AI usage patterns  
**Path**: `~/.copilot/skills/skill-creator/SKILL.md`  
**Compact Rules**:
- Skills are runtime instruction contracts for LLMs, not human docs
- Required sections: frontmatter, Activation Contract, Hard Rules, Decision Gates, Execution Steps, Output Contract, References
- `description` must be quoted, one physical line, trigger-first, ≤250 chars
- Body target: 180-450 tokens; max 700 recommended, 1000 hard max
- No `Keywords` section; keep trigger words in `description`
- References must point to local files

---

### work-unit-commits
**Trigger**: implementation, commit splitting, chained PRs, keeping tests and docs with code  
**Path**: `~/.copilot/skills/work-unit-commits/SKILL.md`  
**Compact Rules**:
- A commit = one deliverable behavior, fix, migration, or docs unit
- Do NOT commit by file type (models → services → tests)
- Tests belong in same commit as the behavior they verify
- Docs belong with the user-visible change they explain
- Reviewer should understand why each commit exists from diff + message

---

## Project Skills

_No project-level skills found (`skills/`, `.agent/skills/`, `.claude/skills/`)._

## Project Conventions

_No `AGENTS.md`, `CLAUDE.md`, `.cursorrules`, or `copilot-instructions.md` found in project root._
