# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Custom YouTube thumbnail generation via Gemini image generation (nano banana)
- `src/thumbnail.py` module with prompt builder, image extraction, and resize
- `upload_thumbnail()` in `youtube.py` for thumbnail upload via YouTube API
- `THUMBNAIL_MODEL` config (default: `gemini-2.0-flash-exp`)
- Pillow dependency for image processing
- 8 new thumbnail tests (95 total)
- MIT LICENSE file
- CONTRIBUTING.md, CODE_OF_CONDUCT.md
- GitHub issue and PR templates
- `pyproject.toml` for project metadata
- `Makefile` for common development commands
- `.github/dependabot.yml` for automated dependency updates
- `.editorconfig` for consistent formatting
- Configurable `OMNI_MODEL` env var for video generation model
- TTS retry with exponential backoff on `NoAudioReceived`
- Text sanitization in `_synth` to avoid TTS failures
- YouTube credential verification before paid video generation
- YouTube token scope checking via Google tokeninfo endpoint
- JSON2Video HTTP error mapping (bad key, quota, connection)
- Transient HTTP 5xx and connection error retries for Gemini video
- `missing_credentials()` helper in `youtube.py`
- `--verify` CLI flag for `src.youtube`

### Changed
- `verify()` no longer fails on upload-only tokens (read scope is optional)
- TTS failures now raise `RuntimeError` instead of propagating `NoAudioReceived`
- YouTube 403 insufficientPermissions now produces actionable scope-specific message
- README rewritten as professional open-source documentation
- Removed fixed header text from captions and JSON2Video renders

### Fixed
- `NoAudioReceived` not caught by `main.py` retry loop (was `Exception`, not `RuntimeError`)
- YouTube verification using channels API that required read scope on upload-only tokens
- JSON2Video connection errors not retried
- Workflow run-mode logic moved from job-level env to `$GITHUB_ENV` (more robust)

## [1.0.0] - 2026-11-09

### Added
- Initial release: full pipeline (script → TTS → video → render → upload)
- Gemini Omni video generation with cost preflight
- JSON2Video as alternate renderer
- Adaptive script/TTS retry based on measured duration
- Animated karaoke captions (ASS)
- GitHub Actions daily cron workflow
- 87 offline/mocked tests
- Topic history to avoid repetition
- Private-first YouTube upload with retry

### Changed
- Word budget changed from 2.5 to 2.0 words/second (conservative)
- Narration overrun tolerance set to 0 (max = TARGET_SECONDS)
- CI failures fixed (DRY_RUN env pinning)
- Target duration: flexible 1–50s (not exact 45s)