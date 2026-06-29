---
title: Setup
nav_order: 2
---

# Setup

## Installation

```bash
pip install ytrix
# or
uv pip install ytrix
```

## Google Cloud Console — OAuth2 Credentials

ytrix needs a Google Cloud project with the YouTube Data API v3 enabled and OAuth 2.0 desktop credentials.

### Step-by-step

1. Go to [Google Cloud Console](https://console.cloud.google.com/).
2. Create a new project (e.g. `ytrix-personal`) or select an existing one.
3. In the left sidebar → **APIs & Services** → **Library**.
4. Search for **YouTube Data API v3** → click **Enable**.
5. Go to **APIs & Services** → **Credentials** → **Create Credentials** → **OAuth client ID**.
6. Choose **Desktop app** as the application type.
7. Give it a name (e.g. `ytrix`) and click **Create**.
8. Note the **Client ID** and **Client Secret**.

### config.toml

Create `~/.ytrix/config.toml`:

```toml
channel_id = "UCxxxxxxxxxxxxxxxxxx"  # your YouTube channel ID

[oauth]
client_id     = "your-client-id.apps.googleusercontent.com"
client_secret = "your-client-secret"
```

Find your channel ID at [youtube.com/account_advanced](https://www.youtube.com/account_advanced).

On first run, `ytrix` opens a browser for OAuth authorisation. The token is cached in `~/.ytrix/token.json`.

## Verifying the Setup

```bash
ytrix config       # shows config status and detected credentials
ytrix ls           # lists your playlists (requires valid token)
```
