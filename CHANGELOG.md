# Changelog

All notable CasePilot changes are documented here.

## [1.0.0] - 2026-07-30

### Added

- New-conversation entry with automatic conversation and collection creation.
- Searchable conversation history with context recovery.
- File-based space knowledge, hybrid retrieval, and explicit lexical fallback.
- Structured test brief with blocking clarification before generation.
- Resumable Agent stages and candidate test-case generation.
- Candidate list/mind-map review and explicit formal collection handoff.
- Formal case collections, revisions, search, structured editing, and persistence.
- QA execution runs that freeze case revisions and retain results, evidence, and audit history.
- Figma V1.0 end-to-end prototype, reusable components, and product documentation derived from tests.

### Changed

- Unified the primary journey as:
  `new conversation → knowledge → brief → candidates → formal assets → execution`.
- Renamed the formal handoff action to “纳入正式集合”.
- Kept execution results exclusively on Execution Runs instead of case assets.
- Updated package and Python project versions to `1.0.0`.

### Fixed

- Clarified candidate/formal-asset isolation and refresh persistence.
- Added deterministic release regression independent of external model availability.
- Synced README, product design, interaction specification, and Figma with current behavior.
