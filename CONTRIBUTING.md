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
# All tests
pytest -xvs

# With coverage
pytest --cov=ytrix --cov-report=term-missing

# Skip integration tests (default)
pytest -m "not integration"
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
