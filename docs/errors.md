# ytrix Error Reference

This document catalogs all error types ytrix handles and how to resolve them.

## Error Categories

### RATE_LIMITED (429)
**What it means**: YouTube is limiting request frequency.

**What ytrix does**:
- Automatic retry with exponential backoff
- After 3 consecutive rate limits on a project, switches to another project in the same quota group

**What you can do**:
- Wait - requests retry automatically
- Use `--throttle 1000` to slow down requests
- Add more projects to your quota group for automatic rotation

### QUOTA_EXCEEDED (403 quotaExceeded)
**What it means**: Daily API quota (10,000 units) is exhausted.

**What ytrix does**:
- Stops retrying (quota resets at midnight PT)
- Switches to another project in the same quota group if available
- Records progress in journal for resume

**What you can do**:
- Wait until midnight PT (use `ytrix quota_status` to see reset time)
- Use `--resume` to continue batch operations tomorrow
- Request quota increase: https://support.google.com/youtube/contact/yt_api_form
- Add more projects to your quota group

### NOT_FOUND (404)
**What it means**: Video or playlist doesn't exist or was deleted.

**What ytrix does**:
- Skips the item
- Continues with remaining items
- Logs the missing resource

**What you can do**:
- Check if the video/playlist exists
- Videos may be private, deleted, or region-locked

### PERMISSION_DENIED (403)
**What it means**: Access denied (not quota related).

**What ytrix does**:
- Skips the item
- Continues with remaining items

**What you can do**:
- Check if you own the playlist you're modifying
- Re-authenticate with `ytrix projects_auth <project>`
- Verify OAuth scopes include write access

### INVALID_REQUEST (400)
**What it means**: Bad request data.

**What ytrix does**:
- Skips the item
- Logs the error

**What you can do**:
- Check if the video is available (not private, deleted, or restricted)
- Some videos can't be added to playlists (live streams, restricted content)

### SERVER_ERROR (5xx)
**What it means**: YouTube API is having issues.

**What ytrix does**:
- Automatic retry with exponential backoff

**What you can do**:
- Wait - usually temporary
- Check https://status.cloud.google.com for outages

### NETWORK_ERROR
**What it means**: Connection failed.

**What ytrix does**:
- Automatic retry with exponential backoff

**What you can do**:
- Check internet connection
- If using proxy, verify it's working

## Quota Costs

| Operation | Units |
|-----------|-------|
| List playlists | 1 |
| List playlist items | 1 |
| Get video details | 1 |
| Create playlist | 50 |
| Add video to playlist | 50 |
| Remove video from playlist | 50 |
| Update playlist metadata | 51 |

Daily limit: 10,000 units per project.

## Common Scenarios

### Batch operation failed mid-way
```bash
# Check journal status
ytrix journal_status

# Resume with same input file
ytrix plists2mlists playlists.txt --resume
```

### Quota exhausted during batch
```bash
# Check quota status
ytrix quota_status

# Wait until midnight PT, then resume
ytrix plists2mlists playlists.txt --resume
```

### Multiple projects for large batches
Configure multiple projects in the same quota group:

```toml
[[projects]]
name = "proj1"
client_id = "..."
client_secret = "..."
quota_group = "batch-work"
priority = 0

[[projects]]
name = "proj2"
client_id = "..."
client_secret = "..."
quota_group = "batch-work"
priority = 1
```

ytrix automatically rotates between them when quota is exhausted.

### Rate limits despite retries
If you see persistent rate limits:
1. Add more projects to your quota group
2. Use `--throttle 2000` for slower requests
3. Reduce concurrent operations
