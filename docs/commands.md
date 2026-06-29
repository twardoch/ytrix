---
title: Command Reference
nav_order: 4
---

# Command Reference

## Global Flags

These flags apply to every command:

| Flag | Description |
|---|---|
| `--verbose` | Enable debug logging |
| `--json-output` | Output results as JSON (for scripting) |
| `--throttle MS` | Milliseconds between API calls (default: 200) |
| `--project NAME` | Force a specific configured project |
| `--quota-group GROUP` | Restrict project selection to a quota group |

## Utility Commands

```bash
ytrix version          # Show installed version
ytrix config           # Show config status and setup guide
ytrix quota_status     # Current quota usage
ytrix quota_status --all-projects   # All projects
ytrix cache_stats      # Disk cache statistics
ytrix cache_clear      # Clear all cached data
ytrix journal_status   # Batch operation progress
ytrix projects         # Show configured projects and quota
ytrix projects_auth NAME   # Authenticate a specific project
ytrix gcp_init NAME    # Create and configure a new GCP project
```

## List Playlists

```bash
ytrix ls                            # Your playlists
ytrix ls --count                    # Include video counts (slower)
ytrix ls --user @handle             # Another channel's playlists
ytrix ls --user UCxxxxxx            # By channel ID
ytrix ls --user @handle --urls      # URLs only (pipe to file)
ytrix --json-output ls              # JSON format
```

## Copy Commands

### Copy one external playlist

```bash
ytrix plist2mlist PLAYLIST_URL_OR_ID
ytrix plist2mlist PLxxxxxx --dry-run         # Preview without creating
ytrix plist2mlist PLxxxxxx --no-dedup        # Skip duplicate check
ytrix plist2mlist PLxxxxxx --privacy unlisted
```

Deduplication: exact match → skip; >75% match → update; otherwise → create new.

### Merge multiple playlists into one

```bash
# playlists.txt: one URL or ID per line
ytrix plists2mlist playlists.txt
```

### Batch copy playlists one-to-one

```bash
ytrix plists2mlists playlists.txt
ytrix plists2mlists playlists.txt --dry-run   # Preview
ytrix plists2mlists playlists.txt --resume    # Resume after interruption
```

### Split a playlist by channel or year

```bash
ytrix plist2mlists PLxxxxxx --by=channel
ytrix plist2mlists PLxxxxxx --by=year
ytrix plist2mlists PLxxxxxx --by=channel --dry-run
```

## YAML Export / Import

```bash
# Export all your playlists
ytrix mlists2yaml                    # Metadata only
ytrix mlists2yaml --details          # Include video details

# Apply YAML edits back
ytrix yaml2mlists playlists.yaml --dry-run   # Preview
ytrix yaml2mlists playlists.yaml             # Apply

# Single playlist
ytrix mlist2yaml PLxxxxxx -o playlist.yaml
ytrix yaml2mlist playlist.yaml
```

### YAML Format

```yaml
playlists:
  - id: PLxxxxxx
    title: "My Playlist"
    description: "About this playlist"
    privacy: public        # public | unlisted | private
    videos:                # only with --details
      - id: dQw4w9WgXcQ
        title: "Video Title"
        channel: "Channel Name"
        position: 0
```

## Subtitle / Transcript Extraction

```bash
ytrix plist2info PLxxxxxx
ytrix plist2info PLxxxxxx --output ./transcripts
ytrix plist2info PLxxxxxx --delay 1.0     # Slower to avoid rate limits
ytrix plists2info playlists.txt           # Multiple playlists
```

Output structure:

```
output_folder/Playlist_Title/
  001_Video_Title.en.srt      # Subtitle file
  001_Video_Title.en.md       # Markdown transcript
  playlist.yaml               # Playlist and video metadata
```

## Error Recovery

**Rate limits (429)**: Automatic exponential-backoff retry. After 3 consecutive failures on a project, ytrix switches to another in the same quota group.

**Quota exhaustion (403)**: Resets at midnight Pacific Time. Resume with:

```bash
ytrix plists2mlists playlists.txt --resume
```

**Review progress**:

```bash
ytrix journal_status
```
