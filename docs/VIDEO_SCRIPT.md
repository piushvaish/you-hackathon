# 90-second Demo Script

## 0:00–0:10 — Problem

Voiceover: Most AI agents search, answer, and stop. Kojable learns why its research was weak, changes how it researches, and proves whether the next answer improves.

Screen: README title.

## 0:10–0:23 — Question

Voiceover: We tested one question: Which is better for AI agent web search, You.com or Exa?

Screen: `python -m kojable_agent --summary` or the beginning of the recorded real run.

## 0:23–0:38 — Run 1

Voiceover: CrewAI orchestrates the flow. You.com retrieves current evidence and produces the research. Clean Data provenance stays attached to the evidence supporting material claims. The first answer had eight evidence weaknesses and scored 63 percent.

Screen: Run 1, 63%, eight weaknesses.

## 0:38–0:54 — Learning

Voiceover: The agent diagnosed missing primary verification and learned a reusable rule: verify material product-capability claims against current primary documentation.

Screen: The learned rule.

## 0:54–1:08 — Real system change

Voiceover: Through One, the agent persisted that learning to a real GitHub Issue, then read the issue back. Run two uses the rule retrieved from GitHub.

Screen: [Issue #1](https://github.com/piushvaish/you-hackathon/issues/1), focusing on Learned rule, Trigger, and Active research rule. Avoid the older numeric baseline in the reused issue; scores come from the comparison artifact.

## 1:08–1:22 — Improvement

Voiceover: It asks the exact same question again. The evidence weaknesses fall from eight to one. The same deterministic evaluator runs in Daytona, and Answer Alignment improves from 63 to 90 percent.

Screen: 63% → 90%, +27 percentage points, IMPROVED.

## 1:22–1:30 — Close

Voiceover: Kojable closes the agent learning loop: observe the failure, change a real system, retrieve the learning, change behavior, and verify the result.

Screen: README architecture.

## Before recording

- [ ] `.env` is closed
- [ ] No API keys are visible
- [ ] No One connection credentials are visible
- [ ] No Daytona keys are visible
- [ ] No GitHub auth token is visible
- [ ] No CrewAI trace access code is visible
- [ ] Terminal is large and readable
- [ ] GitHub Issue #1 is already open in browser
- [ ] README architecture is available in another tab
- [ ] Completed runtime artifacts exist for --summary
- [ ] Summary scores match the narrated run

If current artifacts describe a later run, show the canonical result in DEMO_RESULT.md explicitly as the earlier observed run, or narrate the current result honestly. Do not overwrite current artifacts to manufacture demo scores.

Never show or commit private CrewAI trace URLs or access codes in screenshots, repository files, video, or YouTube descriptions. Rehearse once and adjust pauses to stay within 1–3 minutes.
