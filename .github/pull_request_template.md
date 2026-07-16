## Summary

<!-- What this PR does and why, in a sentence or two. If it resolves a feedback.md task, name it (and remember to mark the task done with a note + commit id). -->

## Changes

<!-- The notable changes, grouped server / client / other as applicable. Call out any schema or data migrations (must be additive + idempotent) and any new settings/config fields. -->

## Verification

<!-- How this was actually verified: unit/smoke tests run, Playwright sweep, live play-through, `tsc`/`vite build` clean, server boot. "Reasoned through" is not verification. -->

## Compatibility checklist

<!-- Delete lines that don't apply. -->

- [ ] No pydantic v2-only APIs in server code (the Android APK pins pydantic v1)
- [ ] No new heavy/native Python deps without Android wheels (Chaquopy build)
- [ ] Turn effects remain reversible (swipe/regenerate/delete unwind cleanly)
- [ ] Existing DBs migrate (additive columns / `CREATE TABLE IF NOT EXISTS` back-fills)
- [ ] CLAUDE.md / feedback.md updated where behavior or architecture changed
