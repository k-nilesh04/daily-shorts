# Contributing to Daily Shorts

Thank you for your interest in contributing! This document provides guidelines for contributing to the project.

## Getting Started

1. **Fork** the repository
2. **Clone** your fork: `git clone https://github.com/<your-username>/daily-shorts.git`
3. **Create a branch**: `git checkout -b feature/your-feature-name`
4. **Set up the environment**:
   ```bash
   python -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   cp .env.example .env
   ```
5. **Run tests**: `python -m unittest discover -s tests`

## Development Guidelines

### Code Style
- Follow [PEP 8](https://peps.python.org/pep-0008/) style guidelines
- Use type hints for function signatures
- Keep functions focused and well-documented
- Use `log = logging.getLogger("shorts")` for logging (from `src.util`)

### Testing
- All new features must include tests
- Tests must pass offline (no real API calls, no credentials needed)
- Tests that need FFmpeg should use `@unittest.skipUnless(shutil.which("ffmpeg"), ...)`
- Mock external APIs (Gemini, Edge-TTS, YouTube) in tests
- Run the full suite before submitting: `python -m unittest discover -s tests`

### Commit Messages
Use [Conventional Commits](https://www.conventionalcommits.org/):
```
feat: add support for custom voice selection
fix: handle empty TTS response gracefully
docs: update README with JSON2Video setup
test: add tests for youtube verify function
refactor: extract retry logic into util module
```

### Pull Request Process
1. Ensure all tests pass locally
2. Update documentation if needed (README, .env.example)
3. Update CHANGELOG.md with your changes
4. Submit a PR with a clear description of what changed and why
5. Link any related issues

### What We're Looking For
- Bug fixes with regression tests
- New TTS voice/language support
- Additional video providers
- Performance improvements
- Documentation improvements
- CI/CD enhancements

### What to Avoid
- Committing secrets, API keys, or credentials
- Adding real API calls to tests
- Breaking existing test contracts without discussion
- Large PRs without prior discussion (open an issue first)

## Reporting Issues

Use the [issue templates](.github/ISSUE_TEMPLATE/) to report bugs or request features. Include:
- Python version and OS
- Steps to reproduce
- Expected vs. actual behavior
- Relevant log output (redact secrets!)

## Code of Conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md). By participating, you agree to uphold this code.