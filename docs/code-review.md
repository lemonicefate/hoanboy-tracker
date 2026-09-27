# Implementation review

Baseline: `46ad9e6260f228fb93707381423f9604f1cfd61f`. Initial implementation: `b4129f8`. Reviewed with `git diff 46ad9e6260f228fb93707381423f9604f1cfd61f...HEAD` in separate Standards and Spec agents. Source: `docs/spec.md` / issue #1. Private patient data was excluded from review.

## Standards

No hard documented standard breach found. Domain terminology and both ADR constraints remain explicit.

Three baseline judgments:

1. Duplicated UTC timestamp helpers in `app.py` and `service.py`. **Resolved:** shared `clock.py`.
2. Divergent change in the browser's single route function. **Resolved:** page renderers own their event wiring; route only dispatches.
3. Positional field-definition tuples obscure mapping edits. **Resolved:** named `FieldDefinition` type.

Separate correctness finding: delayed patient searches could populate controls on a newer route. **Resolved:** route and search generations guard response writes; pagination and restore responses also check route generation. Browser regression covers delayed results after navigation.

## Spec

1. Success notices could overwrite automatic backup errors, violating “備份失敗需可見，不能回報假成功”. **Resolved:** persistent independent banner, refresh recovery, and explicit link before leaving for a report when backup failed. Browser regression covers sync success, refresh, report access and recovery.
2. Already-imported measurements could never gain verified status when evidence arrived, despite “趨勢以所有有效已歸檔量測建立” and saved “映射版本與驗證狀態”. **Resolved:** explicit revalidation API/UI with stored normalization revisions and evidence-derived version IDs; original sources and saved reports remain immutable. API regression covers initial unverified history, later verification, preserved versions and distinct new report.
3. Complete reports and hardware acceptance remain partial. Spec: “完整報告正確性仍是最後驗收條件” and “不以空白占位或猜值宣稱完整報告完成”. **Open:** same-measurement evidence, factory graphical/assessment rules, repeat/restart and clock checks, physical printing. These remain required in `implementation-status.md`; the app only labels its current report as a development draft.

No clear scope creep found.

Totals: Standards — 0 hard violations, 3 maintainability findings and 1 correctness finding resolved. Spec — 2 implementation findings resolved; 1 grouped report/hardware acceptance finding remains open.
