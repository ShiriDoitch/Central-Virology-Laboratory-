# Extra evaluation set: results (no form data)

6 pages, hand-filled truth table (`truth.xlsx`). Measurement only: no rule, threshold or config was tuned on this set, and it is not part 2.

This file deliberately holds **no value from the forms** - no names, ID numbers, dates, center numbers or commitment numbers, and no page crops. Only counts, categories and flags.

Pages evaluated: 6 of 6

## Main fields

| field | n | exact | WRONG-GREEN | wrong-orange | empty |
|---|---|---|---|---|---|
| date | 6 | 3 | 0 | 2 | 1 |
| center | 6 | 2 | 0 | 3 | 1 |
| sender | 6 | 2 | 0 | 4 | 0 |
| commitment (per commitment row) | 7 | 4 | 1 | 1 | 1 |

## ID (reported separately, CLAUDE.md section 16)

| field | n | exact | WRONG-GREEN | wrong-orange | empty |
|---|---|---|---|---|---|
| id | 6 | 4 | 0 | 1 | 1 |

## Names (reported separately from ID)

| field | n | exact | WRONG-GREEN | wrong-orange | empty |
|---|---|---|---|---|---|
| first_name | 6 | 1 | 0 | 0 | 5 |
| last_name | 6 | 1 | 0 | 0 | 5 |

exact = correct value (green or orange)  |  WRONG-GREEN = wrong and not flagged (the metric to minimize)  |  wrong-orange = wrong but flagged  |  empty = no value

## Full category breakdown

| field | confident_ok | confident_wrong | orange_ok | orange_wrong | empty_ok | empty_missed | empty_flagged |
|---|---|---|---|---|---|---|---|
| date | 2 | 0 | 1 | 2 | 0 | 0 | 1 |
| center | 0 | 0 | 2 | 3 | 0 | 0 | 1 |
| sender | 2 | 0 | 0 | 4 | 0 | 0 | 0 |
| commitment | 1 | 1 | 3 | 1 | 0 | 0 | 1 |
| id | 2 | 0 | 2 | 1 | 0 | 0 | 1 |
| first_name | 0 | 0 | 1 | 0 | 0 | 0 | 5 |
| last_name | 0 | 0 | 1 | 0 | 0 | 0 | 5 |

## Every cell that is not exact (categories and flags only)

| page | field | category | flags |
|---|---|---|---|
| 1 | date | empty_flagged | conflict, missing_required_field |
| 1 | commitment | empty_flagged |  |
| 1 | first_name | empty_flagged | conflict, handwritten_unconfirmed, missing_required_field |
| 1 | last_name | empty_flagged | handwritten_unconfirmed, missing_required_field |
| 2 | center | orange_wrong | center_mismatch |
| 2 | sender | orange_wrong | unknown_sender |
| 2 | first_name | empty_flagged | handwritten_unconfirmed, region_not_ok, missing_required_field |
| 2 | last_name | empty_flagged | handwritten_unconfirmed, region_not_ok, missing_required_field |
| 3 | id | empty_flagged | conflict, missing_required_field |
| 3 | first_name | empty_flagged | handwritten_unconfirmed, missing_required_field |
| 3 | last_name | empty_flagged | conflict, handwritten_unconfirmed, missing_required_field |
| 4 | date | orange_wrong | handwritten, date_single_source |
| 4 | center | orange_wrong | center_mismatch |
| 4 | sender | orange_wrong | conflict |
| 4 | first_name | empty_flagged | conflict, handwritten_unconfirmed, missing_required_field |
| 4 | last_name | empty_flagged | conflict, handwritten_unconfirmed, missing_required_field |
| 5 | center | orange_wrong | handwritten |
| 5 | sender | orange_wrong | unknown_sender |
| 5 | commitment | orange_wrong |  |
| 5 | id | orange_wrong | handwritten, region_not_ok |
| 6 | date | orange_wrong | date_kind_unclear, date_single_source |
| 6 | center | empty_flagged | missing_required_field |
| 6 | sender | orange_wrong | unknown_sender |
| 6 | commitment | confident_wrong |  |
| 6 | first_name | empty_flagged | missing_required_field |
| 6 | last_name | empty_flagged | name_label_unknown, missing_required_field |

## Orientation detection

| page | expected | local axis | model reported | rotation applied | attempts | unresolved | straight after rotation |
|---|---|---|---|---|---|---|---|
| 1 | upright | horizontal | 0 | None | 0 | False | True |
| 2 | upright | vertical | 270 | 270 | 1 | False | True |
| 3 | upright | vertical | 270 | 270 | 1 | False | True |
| 4 | upright | horizontal | 0 | None | 0 | False | True |
| 5 | rotated | vertical | 270 | 270 | 1 | False | True |
| 6 | rotated | vertical | 270 | 270 | 1 | False | True |

## Page status

| page | pass 1 model | commitment form | quality | second pass | pass 2 model |
|---|---|---|---|---|---|
| 1 | gemini-3.5-flash-lite | True | ok | run | gemini-3.6-flash |
| 2 | gemini-3.5-flash-lite | False | ok | run | gemini-3.6-flash |
| 3 | gemini-3.5-flash-lite | True | ok | run | gemini-3.6-flash |
| 4 | gemini-3.5-flash-lite | True | ok | run | gemini-3.6-flash |
| 5 | gemini-3.5-flash-lite | True | ok | run | gemini-3.5-flash-lite |
| 6 | gemini-3.5-flash-lite | True | ok | run | gemini-3.5-flash-lite |
