---
title: Config Reference
nav_order: 3
---

# config.toml Reference

All settings live in `~/.ytrix/config.toml`.

## Single-Project (Minimal)

```toml
channel_id = "UCxxxxxxxxxxxxxxxxxx"

[oauth]
client_id     = "your-client-id.apps.googleusercontent.com"
client_secret = "your-client-secret"
```

## config.toml Keys

| Key | Type | Required | Description |
|---|---|---|---|
| `channel_id` | string | Yes | Your YouTube channel ID (starts with `UC`) |
| `[oauth].client_id` | string | Yes (single project) | OAuth 2.0 Desktop client ID |
| `[oauth].client_secret` | string | Yes (single project) | OAuth 2.0 Desktop client secret |
| `[[projects]]` | array | No | Multiple GCP projects for quota rotation |

## Multi-Project Setup

YouTube API quota is 10,000 units/day per GCP project. For separate legitimate use cases, configure multiple projects:

```toml
channel_id = "UCxxxxxxxxxx"

[[projects]]
name          = "personal"
client_id     = "personal-client-id.apps.googleusercontent.com"
client_secret = "personal-secret"
quota_group   = "personal"
priority      = 0

[[projects]]
name          = "client-work"
client_id     = "client-client-id.apps.googleusercontent.com"
client_secret = "client-secret"
quota_group   = "client"
priority      = 0
```

### `[[projects]]` Keys

| Key | Type | Description |
|---|---|---|
| `name` | string | Unique project name (used with `--project`) |
| `client_id` | string | OAuth 2.0 client ID for this project |
| `client_secret` | string | OAuth 2.0 client secret for this project |
| `quota_group` | string | Group name for context switching |
| `priority` | int | Lower = preferred; 0 is highest |

### Context Switching

ytrix switches to another project in the same `quota_group` when:

- Daily quota is exhausted (HTTP 403 `quotaExceeded`)
- Rate limits persist after retries (HTTP 429)

**Important**: Do NOT use multiple projects to bypass quota limits for one use case — this violates Google's ToS. Request higher quota via the [YouTube API quota extension form](https://support.google.com/youtube/contact/yt_api_form).

## Quota Costs

| Operation | Units |
|---|---|
| Playlist create | 50 |
| Playlist update | 50 |
| Playlist delete | 50 |
| Video add / remove | 50 each |
| Playlist list (per page) | 1 |
| Video metadata list | 1 |

A batch copy of 10 playlists × 100 videos ≈ 50,500 units (needs ~5 projects at 10k each).

## Token Storage

| Path | Contents |
|---|---|
| `~/.ytrix/token.json` | OAuth token (single project) |
| `~/.ytrix/tokens/{name}.json` | Per-project OAuth tokens |
| `~/.ytrix/quota_state.json` | Daily quota usage per project |
