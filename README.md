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

### Multi-Project Setup (For Heavy Usage)
YouTube API has a 10,000 units/day quota per project. For separate, legitimate use cases (e.g., personal vs client work), configure multiple projects:

```toml
channel_id = "UCxxxxxxxxxx"

[[projects]]
name = "personal"
client_id = "personal-client-id.apps.googleusercontent.com"
client_secret = "personal-secret"
quota_group = "personal"  # Group for context switching
priority = 0               # Lower = preferred

[[projects]]
name = "client-work"
client_id = "client-client-id.apps.googleusercontent.com"
client_secret = "client-secret"
quota_group = "client"
priority = 0
```

**Context Switching**: ytrix automatically switches to another project in the same `quota_group` when:
- Daily quota is exhausted (403 quotaExceeded)
- Rate limits persist after retries (429 Rate Limited)

**Commands**:
```bash
ytrix projects                    # Show all projects and quota status
ytrix projects_auth personal      # Authenticate a specific project
ytrix --project personal ...      # Force use specific project
ytrix --quota-group client ...    # Restrict to projects in group
```

**Important**: Do NOT use multiple projects to bypass quota limits for one use case—this violates Google's ToS. Request more quota: [Quota extension form](https://support.google.com/youtube/contact/yt_api_form).

### Quota Management
```bash
ytrix quota_status                # Show current quota usage
ytrix quota_status --all-projects # Show all projects
```

Quota costs:
- **Playlist create**: 50 units
- **Video add/remove**: 50 units each
- **Playlist update**: 51 units

A batch copy of 10 playlists with 100 videos each ≈ 50,500 units (5 projects at 10k each).

### Error Recovery
**Rate Limits (429)**: Automatic retry with exponential backoff. After 3 consecutive rate limits on a project, ytrix switches to another project in the same quota group.

**Quota Exhaustion (403)**: Cannot retry until midnight PT. Use `--resume` to continue:
```bash
ytrix plists2mlists playlists.txt --resume
```

**Failed Operations**: The journal tracks all operations. Review status:
```bash
ytrix journal_status
```

## Global Flags
```bash
ytrix --verbose ...        # Enable debug logging
ytrix --json-output ...    # Output results as JSON (for scripting)
ytrix --throttle 500 ...   # Slower API calls (ms between requests)
ytrix --project main ...   # Force specific project (multi-project setup)
ytrix --quota-group prod   # Restrict project selection to a quota group
ytrix version              # Show version
ytrix config               # Show config status and setup guide
ytrix ls                   # List your playlists
ytrix cache_stats          # Show cache statistics
ytrix cache_clear          # Clear all cached data
ytrix journal_status       # Show batch operation progress
ytrix projects             # Show configured projects and quota
ytrix <command> --help     # Help for any command
```

## Usage
### List your playlists
```bash
ytrix ls                      # Show all your playlists
ytrix ls --count              # Include video counts (slower)
ytrix --json-output ls        # JSON format for scripting
```

### List another channel's playlists
```bash
ytrix ls --user @channelhandle           # By handle
ytrix ls --user UCxxxxxx                 # By channel ID
ytrix ls --user @channelhandle --urls    # URLs only (pipe to file)
```

### Copy external playlist to your channel
```bash
ytrix plist2mlist https://www.youtube.com/playlist?list=PLxxxxxx
ytrix plist2mlist PLxxxxxx --dry-run    # Preview without creating
ytrix plist2mlist PLxxxxxx --no-dedup   # Skip duplicate check
ytrix plist2mlist PLxxxxxx --privacy unlisted  # public, unlisted, private
```

Dedup: exact match skips, >75% match updates, otherwise a new playlist.

### Merge multiple playlists
```bash
# playlists.txt contains one URL or ID per line
ytrix plists2mlist playlists.txt
```

### Batch copy playlists one-to-one
```bash
ytrix plists2mlists playlists.txt
ytrix plists2mlists playlists.txt --dry-run   # Preview without creating
ytrix plists2mlists playlists.txt --resume    # Resume interrupted batch
```

Features:
- **Deduplication**: Skips playlists that already exist with identical videos
- **Smart matching**: Updates existing playlists if >75% videos match
- **Journaling**: Tracks progress, resumes after interruption or quota limits

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
```

### Apply YAML edits to your playlists
```bash
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

### Extract playlist info with subtitles
```bash
ytrix plist2info PLxxxxxx                         # Extract single playlist
ytrix plist2info PLxxxxxx --output ./transcripts  # Custom output directory
ytrix plist2info PLxxxxxx --delay 1.0             # Slower to avoid rate limits
```

Creates a folder structure:
```
output_folder/Playlist_Title/
  001_Video_Title.en.srt      # Subtitle file
  001_Video_Title.en.md       # Markdown transcript
  playlist.yaml               # Playlist and video metadata
```

The `playlist.yaml` includes duration info:
```yaml
id: PLxxxxxx
title: "Playlist Title"
video_count: 10
total_duration: 3600          # Total seconds
total_duration_formatted: "1:00:00"
videos:
  001_Video_Title:
    id: abc123
    duration: 360             # Video seconds
    duration_formatted: "6:00"
    ...
```

### Extract info from multiple playlists
```bash
ytrix plists2info playlists.txt                   # Process all playlists
ytrix plists2info playlists.txt --output ./info   # Custom output directory
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
