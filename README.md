# ytrix

YouTube playlist management CLI. Copy playlists between channels, split by criteria, edit via YAML.

## Installation

```bash
uv pip install -e .
```

## Configuration

Run `ytrix config` to see config status and a detailed setup guide.

Create `~/.ytrix/config.toml`:

```toml
channel_id = "UCxxxxxxxxxxxxxxxxxx"  # Your YouTube channel ID

[oauth]
client_id = "your-client-id.apps.googleusercontent.com"
client_secret = "your-client-secret"
```

### Getting YouTube API Credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project or select existing
3. Enable YouTube Data API v3
4. Create OAuth 2.0 credentials (Desktop app)
5. Download and note client_id and client_secret

First run will open browser for OAuth authorization. Token is cached in `~/.ytrix/token.json`.

## Global Flags

```bash
ytrix --verbose ...      # Enable debug logging
ytrix --json-output ...  # Output results as JSON (for scripting)
ytrix version            # Show version
ytrix config             # Show config status and setup guide
ytrix ls                 # List your playlists
ytrix cache_stats        # Show cache statistics
ytrix cache_clear        # Clear all cached data
ytrix <command> --help   # Help for any command
```

## Usage

### List your playlists

```bash
ytrix ls                      # Show all your playlists
ytrix ls --count              # Include video counts (slower)
ytrix --json-output ls        # JSON format for scripting
```

### Copy external playlist to your channel

```bash
ytrix plist2mlist https://www.youtube.com/playlist?list=PLxxxxxx
ytrix plist2mlist PLxxxxxx  # ID also works
ytrix plist2mlist PLxxxxxx --dry-run    # Preview without creating
ytrix plist2mlist PLxxxxxx --no-dedup   # Skip duplicate check
```

The `--dedup` flag (default: True) checks for existing playlists:
- **Exact match**: Skips creation, returns existing playlist URL
- **Partial match (>75%)**: Updates existing playlist with missing videos
- **No match**: Creates new playlist

### Merge multiple playlists

```bash
# playlists.txt contains one URL or ID per line
ytrix plists2mlist playlists.txt
ytrix plists2mlist playlists.txt --dry-run  # Preview, shows duplicate detection
```

### Batch copy playlists one-to-one

```bash
# Copy each source playlist to a separate playlist on your channel
ytrix plists2mlists playlists.txt
ytrix plists2mlists playlists.txt --dry-run   # Preview without creating
ytrix plists2mlists playlists.txt --resume    # Resume interrupted batch
```

Features:
- **Deduplication**: Skips playlists that already exist with identical videos
- **Smart matching**: Updates existing playlists if >75% videos match
- **Journaling**: Tracks progress, resumes after interruption or quota limits
- **Retry with backoff**: Handles API rate limits gracefully

### Split playlist by channel or year

```bash
ytrix plist2mlists https://youtube.com/playlist?list=PLxxx --by=channel
ytrix plist2mlists PLxxx --by=year
ytrix plist2mlists PLxxx --by=channel --dry-run  # Preview without creating
```

### Export all your playlists to YAML

```bash
ytrix mlists2yaml                    # Playlist metadata only
ytrix mlists2yaml --details          # Include video details
ytrix mlists2yaml -o my_playlists.yaml
```

### Apply YAML edits to your playlists

```bash
# Edit the YAML, then:
ytrix yaml2mlists my_playlists.yaml --dry-run  # Preview changes
ytrix yaml2mlists my_playlists.yaml            # Apply changes
```

### Export single playlist to YAML

```bash
ytrix mlist2yaml PLxxxxxx -o playlist.yaml
```

### Apply edits to single playlist

```bash
ytrix yaml2mlist playlist.yaml
```

## Terminology

- **plist**: Any YouTube playlist
- **mlist**: Playlist on your channel ("my list")

## YAML Format

```yaml
playlists:
  - id: PLxxxxxx
    title: "My Playlist"
    description: "About this playlist"
    privacy: public  # public, unlisted, private
    videos:  # only with --details
      - id: dQw4w9WgXcQ
        title: "Video Title"
        channel: "Channel Name"
        position: 0
```

## Dependencies

- YouTube Data API v3 (OAuth2 for writes)
- yt-dlp (metadata extraction, no API quota)

## License

MIT
