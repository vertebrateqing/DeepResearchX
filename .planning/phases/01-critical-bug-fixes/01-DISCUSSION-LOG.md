# Phase 1: Critical Bug Fixes - Discussion Log (Assumptions Mode)

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions captured in CONTEXT.md — this log preserves the analysis.

**Date:** 2026-04-25
**Phase:** 01-critical-bug-fixes
**Mode:** assumptions
**Areas analyzed:** Bug fixes, Code style

## Assumptions Presented

### Bug fix approach
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| Surgical one-line fixes for each bug | Confident | CONCERNS.md provides exact file paths, line numbers, and fix descriptions |
| Chinese error messages for user-facing output | Likely | Rest of codebase uses Chinese for prompts and user-facing text |
| No API signature changes | Confident | All bugs are internal logic errors, not interface issues |

### Testing
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| Add unit tests for each fixed bug | Likely | Existing test suite (23 tests) covers similar patterns |
| Tests must pass without external API keys | Likely | `tests/unit/` uses mocks; no real API calls in unit tests |

## Corrections Made

No corrections — all assumptions confirmed by user's initial request: "修复你扫描出的bug和一些风险项，暂时使用ChromaDB不对向量数据库选型做变更"

## Auto-Resolved

Not applicable — not in auto mode.

## External Research

No external research needed — codebase audit (CONCERNS.md) provides sufficient detail for all fixes.
