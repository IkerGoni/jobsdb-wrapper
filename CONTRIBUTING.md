# Contributing to jobsdb-wrapper

Thank you for your interest in contributing!

## Development Setup

```bash
# Clone the repo
git clone https://github.com/igoni/jobsdb-wrapper.git
cd jobsdb-wrapper

# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install in development mode with dev dependencies
pip install -e ".[dev]"
```

## Running Tests

```bash
# Run all tests
python -m pytest tests/ -v

# Run with coverage
python -m pytest tests/ --cov=jobsdb_wrapper --cov-report=term-missing

# Run specific test file
python -m pytest tests/test_http.py -v
```

## Code Quality

```bash
# Lint with ruff
ruff check src/ tests/

# Type check with mypy
mypy src/jobsdb_wrapper --ignore-missing-imports

# Format with ruff
ruff format src/ tests/
```

## Live Testing

```bash
# Test CLI search (requires internet)
python -m jobsdb_wrapper.cli search "python" --page-size 3

# Test CLI job detail
python -m jobsdb_wrapper.cli job <JOB_ID> --markdown

# Run contract doctor
python -m jobsdb_wrapper.cli doctor
```

## Making Changes

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Make your changes
4. Run tests and linting
5. Commit with conventional commits: `git commit -m "feat: add new feature"`
6. Push and open a PR

## Commit Convention

This project uses [Conventional Commits](https://www.conventionalcommits.org/):

- `feat:` — New feature
- `fix:` — Bug fix
- `docs:` — Documentation only
- `refactor:` — Code restructure
- `test:` — Test additions/changes
- `chore:` — Maintenance
- `perf:` — Performance improvement

## Pull Request Guidelines

- Keep PRs focused and small
- Update tests for new functionality
- Update documentation if user-facing changes
- Ensure CI passes
- Link related issues

## Reporting Issues

- Use GitHub Issues
- Include reproduction steps
- Include Python version, OS, package version
- Include CLI command or code snippet that fails
- Do not include sensitive data (cookies, tokens, personal info)

## Security

- Do not commit cookies, session files, or credentials
- Report security issues privately via GitHub Security Advisories
- This package accesses a private undocumented API — use responsibly

## License

By contributing, you agree that your contributions will be licensed under the MIT License.