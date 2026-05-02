Read `operations/sync.md` and execute the sync procedure defined there.

Focus hints from the user: $ARGUMENTS

- If hints are empty, do a full baseline sweep across all 7 artifact axes (code, prompts, specs, decisions.md, CLAUDE.md, README.md, deployment config).
- If hints are present, prioritize findings matching them, but still do a baseline pass so findings outside the hints aren't silently dropped.

Follow the output format and approval flow (D8: propose, don't commit) specified in `operations/sync.md`. Do not edit any files during the sync run — produce only the report. Sync-driven edits happen as normal conversation turns afterward, committed with a `sync:` prefix.
