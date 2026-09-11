# Hackathon Submission

## Project

Kojable — Self-Improving Answer Alignment Agent

## Challenge

Self-Improving and Learning Agents

## Public GitHub

[Repository](https://github.com/piushvaish/you-hackathon)

## YouTube

[ADD YOUTUBE URL]

## 200-word description

Kojable is a self-improving answer-alignment agent that does more than search the web and generate an answer. We demonstrate it with one difficult product-comparison question: “Which is better for AI agent web search, You.com or Exa?” CrewAI orchestrates the workflow. You.com Search and Research APIs gather current web evidence and produce a structured answer and claim ledger. Each evidence record carries Clean Data provenance, including source URL, publisher, retrieval time, and supporting passage. Daytona runs a deterministic alignment scorer in an isolated sandbox, so the model does not grade itself. After the first run, the agent audits weak claims, identifies the highest-impact research failure, and creates a reusable research rule. One then persists that rule to a real GitHub Issue and reads it back. The second run must use the externally retrieved rule before researching the exact same question again. In our live test, Answer Alignment improved from 63% to 90%, while evidence weaknesses fell from eight to one. The key innovation is closed-loop learning: the agent observes a failure, changes a real external system, retrieves its own learned memory, changes its research behavior, and verifies whether the new answer is actually better without changing the original buyer question itself.

## Suggested repository description

Self-improving agent that audits its evidence, persists learned research rules, retries, and measures whether the answer improves.
