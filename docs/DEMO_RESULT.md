# Verified Live Demo Result

Canonical successful run supplied by the project owner; later runs can differ.

Question: Which is better for AI agent web search, You.com or Exa?

| Metric | Run 1 | Run 2 |
|---|---:|---:|
| Answer Alignment | 63% | 90% |
| Evidence weaknesses | 8 | 1 |
| Material claims | 10 | 10 |

Improvement: **+27 percentage points**. Status: **IMPROVED**.

Learning trigger: `missing_primary_verification`

> Verify material product-capability claims against the product's current primary documentation before concluding.

External memory: [GitHub Issue #1](https://github.com/piushvaish/you-hackathon/issues/1).

The GitHub Issue demonstrates persistent external memory. The comparison artifact is the authoritative source for Run 1/Run 2 scores. The reused issue may record an older baseline score. The canonical run completed CrewAI orchestration, One persistence and read-back, Run 2 using the retrieved rule, both Daytona evaluations, and comparison generation.

The offline summary displays current runtime artifacts, which may reflect a later improved, unchanged, or regressed run. The sanitized example preserves this canonical result and is never substituted for runtime data.
