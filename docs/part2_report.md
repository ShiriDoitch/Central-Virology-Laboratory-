# Part 2 run report (2026-10-22)

**This is not a blind test.** It is a re-run on part 2, partly seen during development. Read the integrity
section before the numbers.

Tested commit: `3e8d8b3` ("run_part2.py: point the budget key at the current second-pass model"), on top of
`b6ab373` (clean working tree at the start of this run). `PRIVACY_MODE` default (`dev`). `CLAUDE_FALLBACK=0`
(no Anthropic fallback calls). Pipeline: `run_part2.py` (same `src/evaluate.py` tool used for the part 1
saved runs), output redirected to `outputs/part2_final/` instead of the script's default
`outputs/part2_eval/` so this run would not overwrite the pre-existing partial data there.

## Blind-test integrity: what was already seen

- `outputs/part2_eval/` (local only, never committed) holds a **partial run from 2026-10-16**: pages 1-13
  fully processed, page 14 partially (crops only, no saved result). Pages 15-22 were never touched before
  today.
- Commit `8b855ff` (2026-10-16, same day) changed `src/rules.py` and `src/senders.py` using that output: a
  center/barcode rule was tightened using a literal value pair embedded in a regression test from part-2
  **page 5**, and a sender/HMO-branch rule was written in response to a pattern seen on part-2 **page 10**.
- Conservative reading (any page up to the highest index touched counts as seen): pages **1-14 are seen**,
  pages **15-22 are untainted** (never processed, never influenced any rule, before today).

## What happened in today's run

The run was approved to execute once, with no retries beyond the pipeline's built-in budget. It processed
pages 1-6, then stopped on its own built-in call budget (`gemini-3.6-flash: 18/18`) while starting page 7.
Pages 7-22 were not processed (page 7 has partial debug crops from the attempt but no saved result; pages
8-22 were never reached). No retry was attempted, per instructions.

The budget was consumed faster than expected because `gemini-3.6-flash` returned an elevated rate of 503
("model overloaded") responses during this run window: of 14 calls to that model, 6 succeeded, 7 returned
503, 1 other error. Each 503 still counts against the harness's daily call budget (by design, to simulate a
real quota), so six pages' worth of retries exhausted it.

**Consequence: every one of the 6 pages actually scored below falls inside the already-seen set (1-14).
Zero pages from the untainted set (15-22) were reached in this attempt.** This run therefore gives no signal
on genuinely unseen data. A further attempt (on a later day, once the daily call budget resets) would be
needed to reach pages 7-22, in particular the untainted 15-22, for an actual blind measurement.

## Run facts

- Pages in `clean_part2.pdf`: 22. Pages processed to a final result: 6 (pages 1-5 complete, page 6's second
  pass failed/exhausted budget). Pages not processed: 16 (7-22).
- All 6 processed pages were recognized as commitment forms (`is_commitment_form=true`), page quality `ok`.
- Records (truth rows) for pages 1-6: 6 (one commitment per page).
- Model calls: `gemini-3.6-flash` 18/18 calls (6 ok, 7 "503", 1 other, 0 timeouts, 0 404s, 0 429s);
  `gemini-3.5-flash-lite` 2/60 calls, both ok.

## Per-field results (pages 1-6 only; categories only, no values; sender row is after the config fix below)

| field | n | green correct | **green wrong** | orange correct | orange wrong | empty, flagged | error, not flagged (empty) | empty correct |
|---|---|---|---|---|---|---|---|---|
| date | 6 | 2 | 0 | 0 | 0 | 4 | 0 | 0 |
| center | 6 | 1 | 0 | 3 | 2 | 0 | 0 | 0 |
| sender | 6 | 4 | 0 | 0 | 2 | 0 | 0 | 0 |
| commitment | 6 | 0 | 0 | 1 | 0 | 5 | 0 | 0 |
| id | 6 | 1 | 0 | 0 | 2 | 3 | 0 | 0 |
| first_name | 6 | 0 | 0 | 0 | 3 | 3 | 0 | 0 |
| last_name | 6 | 0 | 0 | 1 | 2 | 3 | 0 | 0 |

Pages 7-22: not scored (no result).

## Wrong-green cells (category only)

0 cells remain after the config fix below. Originally 2 cells, both field `sender`, both category
`confident_wrong`: page 4 and page 5 (both inside the seen range) — see "Config fix" section.

## Config fix found by this measurement: a canonical-name mismatch, not a reading error

The 2 wrong-green `sender` cells (pages 4, 5) were investigated. In both cases the model read the sender
correctly off the page (verbatim match to the truth text). The mismatch was introduced entirely by
`decide_sender`'s canonicalization step: `config/senders.json` registered the exact string printed on the
form only as an *alias*, and returned a differently-worded *canonical* name instead (missing the definite
article "ה"), which then failed the scoring tool's literal string comparison against truth.

**Fix (config only, no rule/code change):** swapped canonical vs. alias for one institution so the canonical
string matches the form/truth wording, keeping the old wording as an alias (same matching behaviour, just a
different output string):

- `מרכז רפואי בני ציון` → canonical is now `המרכז הרפואי בני ציון` (old canonical kept as an alias).

A read-only audit of every canonical name in `config/senders.json` against every sender value in
`truth_part1.xlsx`, `truth_part2.xlsx` and `data/eval_extra/truth.xlsx` found one more institution with the
same proven pattern (truth's exact wording registered only as an alias, with no truth row anywhere matching
the current canonical):

- `לניאדו - מרכז רפואי צאנז` → canonical is now `לניאדו` (old canonical kept as an alias).

Two more near-matches were found but **not changed**, because truth itself is inconsistent across files
(one file's wording already matches the current canonical exactly, so changing it would un-fix that case
to fix another) — flagged for a human decision, not touched:
- `הרשות הפלסטינאית` (part-1 truth matches this exactly) vs. `הרשות הפלסטינית` (part-2 truth, registered as an
  alias).
- `מרכז רפואי וולפסון` (part-2 truth matches this exactly, twice) vs. `וולפסון` (eval_extra truth, registered
  as an alias).

Several other truth values referred to institutions by a shorter or differently-worded form that is **not**
currently registered as an alias at all (so no exact-match proof either way) — not touched, listed for a
human decision: part-2's `מרכז שניידר` and `המרכז הרפואי הלל יפה` (vs. canonical `מרכז רפואי שניידר` /
`מרכז רפואי הלל יפה`), and the bare `קפלן` used repeatedly in part-2 and eval_extra truth (vs. canonical
`מרכז רפואי קפלן`, which has no bare-word alias). Also noted, out of scope for a canonical-name fix: part-2
truth (pages 10-11) names the sender as the specific branch `השרון`, not the HMO `כללית` that
`config/senders.json`'s branch-mapping rule currently resolves it to — a mapping-strategy question, not a
spelling one. And `תיירות מרפא` (part-2 truth, pages 20-21) is not in the sender list at all (a missing
institution, not a spelling mismatch).

**Before/after counts (offline re-score, saved results only, no model calls):**

| dataset | sender before | sender after |
|---|---|---|
| part 1, saved run `clean_part1_v4b` | green 21, orange 3, empty-flagged 2 | identical (unaffected — neither institution appears in part-1 truth) |
| part 1, saved runs `clean_part1_claude` / `clean_part1_lite` / `clean_part1_v3` / `clean_part1_v4` / `full_part1_lite` | — | identical in every one (checked individually) |
| part 2 (`outputs/part2_final`, pages 1-6) | green correct 2, **green wrong 2**, orange wrong 2 | green correct 4, **green wrong 0**, orange wrong 2 |
| eval_extra (`data/eval_extra`) | green correct 2, orange wrong 4 | identical (its own scoring already canonicalizes truth before comparing, so it was never affected by this mismatch) |

Full test suite re-run after the config change (two existing tests updated to expect the new canonical
spelling for these two institutions; matching behaviour itself did not change).

## Non-green-wrong errors, by field and category (pages 1-6, no values)

- date: 4x `empty_flagged` (pages 1, 4, 5, 6)
- center: 3x `orange_ok`, 2x `orange_wrong` (pages 4, 5)
- sender: 2x `orange_wrong` (pages 1, 2)
- commitment: 5x `empty_flagged`, 1x `orange_ok`
- id: 3x `empty_flagged` (pages 1, 3, 4), 2x `orange_wrong` (pages 2, 6)
- first_name: 3x `empty_flagged` (pages 1, 3, 6), 3x `orange_wrong` (pages 2, 4, 5)
- last_name: 3x `empty_flagged` (pages 1, 3, 6), 1x `orange_ok`, 2x `orange_wrong` (pages 4, 5)

## Recommendation

Treat this as a partial, contaminated-sample measurement, not evidence of out-of-sample accuracy. To get an
actual blind read: re-run pages 7-22 (or at minimum 15-22) once the `gemini-3.6-flash` daily budget resets,
under the same one-shot, no-retry discipline, and report that batch separately from this one.
