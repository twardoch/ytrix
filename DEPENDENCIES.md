# Dependencies

## Core Dependencies

| Package | Version | Purpose | Justification |
|---------|---------|---------|---------------|
| fire | >=0.5.0 | CLI framework | Minimal config, auto-generates help from docstrings |
| rich | >=13.0.0 | Console output | Progress bars, colored output, tables |
| google-api-python-client | >=2.100.0 | YouTube Data API v3 | Official Google client, required for playlist writes |
| google-auth-oauthlib | >=1.1.0 | OAuth2 authentication | Required for YouTube API user authorization |
| yt-dlp | >=2024.1.0 | Metadata extraction | No API quota usage, handles edge cases (private/deleted) |
| pyyaml | >=6.0 | YAML parsing | Standard, well-maintained, safe_load by default |
| pydantic | >=2.0.0 | Config validation | Type-safe config loading, clear error messages |
| loguru | >=0.7.0 | Logging | Clean API, --verbose flag support |
| tenacity | >=8.2.0 | Retry with backoff | Handles API rate limits, simple decorator API |

## Development Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| pytest | >=9.0.0 | Testing framework |
| ruff | latest | Linting and formatting |
| mypy | latest | Type checking |

## Dependency Rationale

### Why yt-dlp + YouTube API (not just one)?

- **yt-dlp** for reads: Zero API quota usage, faster for bulk operations, handles edge cases
- **YouTube API** for writes: Only way to create/modify playlists on user's channel

### Why Fire over Click/Typer?

- Fire auto-generates CLI from class methods with no decorators
- Docstrings become help text automatically
- Simpler code, fewer lines

### Why PyYAML over ruamel.yaml?

- Simpler API, well-maintained
- Don't need round-trip comment preservation
- Standard library feel

### Why Pydantic over dataclasses for config?

- Better validation error messages
- Handles nested structures (OAuthConfig within Config)
- Type coercion built-in

### Why Loguru over stdlib logging?

- Zero-config setup with sensible defaults
- Cleaner API (no getLogger boilerplate)
- Better formatting and colorization out of the box
- Easy verbose/debug toggle with `logger.remove()`/`logger.add()`

### Why tenacity over Huey/Celery/custom retry?

- Simple decorator-based API (`@retry`)
- Built-in exponential backoff with jitter
- No external services (Redis, RabbitMQ)
- Popular (>5k GitHub stars), well-maintained
- Perfect for CLI tools with API rate limits
