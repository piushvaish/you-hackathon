# Kojable — Self-Improving Answer Alignment Agent

An agent that measures the evidence behind its own answer, learns from research failures, changes its research strategy, and proves whether the next answer improves.

## Challenge

Self-Improving and Learning Agents.

## Demo question

> Which is better for AI agent web search, You.com or Exa?

## Self-improving loop

```text
Research
  ↓
Audit
  ↓
Measure
  ↓
Learn
  ↓
Persist to GitHub through One
  ↓
Read memory
  ↓
Retry the same question
  ↓
Measure again
```

The auditor uses one additional structured You.com Research call and the same
finite verdict/failure vocabulary for both runs. The learner deterministically
selects one reusable research-method rule from the highest-priority observed
failure. It never learns which vendor to prefer.

## Why GitHub?

The learned rule is persisted to a real external system rather than remaining
hidden in process memory. The second research run reads the rule back from the
created GitHub Issue through One before rerunning the exact same question. A
local `learning.json` is only a trace; it is never the authoritative memory.

## Architecture

```text
CrewAI Flow
     ↓
You.com Search + Research
     ↓
Evidence + provenance
     ↓
Clean Data gate
     ↓
You.com evidence audit
     ↓
Daytona deterministic score (Run 1)
     ↓
Learn → One → GitHub Issue
     ↓
One → read GitHub Issue
     ↓
Run 2 → audit → Daytona → compare
```

CrewAI Flow is the real orchestration layer. Its PR2 stages enforce
`baseline → audit1 → score1 → learn → persist → retrieve → run2 → audit2 → score2 → compare → save`.

## Partner roles

**You.com** — Live web search and grounded, structured research.

**CrewAI** — Orchestrates the complete learning loop.

**Daytona** — Runs the same deterministic Answer Alignment evaluator for both
runs in isolated sandboxes. A live run never silently falls back to local
scoring.

**One** — Discovers current GitHub actions, reads each action's knowledge, and
persists/retrieves learned behavior without exposing GitHub credentials to the
application.

**Clean Data** — Every evidence record retains the source URL, publisher domain, retrieval time, actual retrieved highlights, any available publication/update date, and source type. The validator reports `valid`, `incomplete`, or `invalid`; it never fabricates a date or drops conflicting public product evidence. Missing publication dates are incomplete rather than invalid. No personal information is collected.

## Windows setup

From the repository root:

Use Python 3.11, 3.12, or 3.13 (current CrewAI releases do not support Python 3.14).

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
python -m pip install -e ".[dev]"

Copy-Item .env.example .env
```

Populate the root `.env` manually with `YDC_API_KEY` and `DAYTONA_API_KEY`.
`ONE_SECRET` is optional when One authentication is already managed by the CLI.
Never commit `.env`.

Install and authenticate using the current One CLI, then connect GitHub:

```powershell
npm install -g @withone/cli
one init
one add github
one --agent list --search github
```

Setup is intentionally manual because `one init` and `one add github` are
interactive. The application never performs them automatically.

## Preflight

```powershell
python -m kojable_agent --preflight
```

Preflight checks Python, `.env`, partner SDKs, One authentication, an active
GitHub connection, and inferred issue-write access. It is read-only and never
creates a test issue.

## Run

```powershell
python -m kojable_agent --baseline
python -m kojable_agent --loop
```

With no mode flag, the backwards-compatible PR1 baseline still runs. `--loop`
runs the complete PR2 workflow. It uses three neutral searches in each run and
adds at most two verification queries derived from the actual Run 1 failure.
The canonical buyer question never changes, and neither vendor receives a
domain boost.

## Output

```text
data/run_1.json
data/audit_1.json
data/learning.json
data/run_2.json
data/audit_2.json
data/comparison.json
```

Runtime output is ignored by Git. `comparison.json` records both scores, the
honest delta/status, and the genuine GitHub Issue reference when returned.

## Answer Alignment

Each material claim earns one point for referencing evidence, one point when at
least one referenced record passes the Clean Data gate, and one point when the
auditor verdict is `verified`. Weak, conflicted, and unsupported verdicts do not
receive the verification point. Failure counts remain visible instead of being
hidden behind penalties. Run 1 and Run 2 use the identical formula in Daytona.

## Expected external effect

A successful `--loop` run creates one GitHub Issue in
`piushvaish/you-hackathon` containing the research rule learned from Run 1. The
issue is intentionally retained as evidence that the agent changed a real
external system. If creation or read-back fails, Run 2 aborts instead of using a
local fallback.
