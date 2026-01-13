# Contributing to ytrix

## Development Setup

```bash
# Clone and install
git clone https://github.com/twardoch/ytrix.git
cd ytrix
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
```

## Running Tests

```bash
# All checks (lint, type, unit, integration, functional)
./test.sh

# Unit tests only
uvx pytest -xvs

# With coverage
uvx pytest --cov=ytrix --cov-report=term-missing

# Skip integration tests (default)
uvx pytest -m "not integration"
```

## Code Quality

```bash
# Lint and format
uvx ruff check --fix .
uvx ruff format .

# Type check
uvx mypy ytrix/
```

## Before Submitting

1. Run `pytest` - all tests must pass
2. Run `ruff check` - no lint errors
3. Run `ruff format` - code is formatted
4. Update CHANGELOG.md if adding features
