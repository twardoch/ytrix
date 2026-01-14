# Part 3: Quota Optimization Strategies

## Quota Cost Reference

| Operation | Cost | Notes |
|-----------|------|-------|
| `playlists.list` | 1 | Batch up to 50 IDs |
| `playlistItems.list` | 1 | Use maxResults=50 |
| `playlists.insert` | 50 | Create new playlist |
| `playlists.update` | 50 | Modify metadata |
| `playlists.delete` | 50 | Remove playlist |
| `playlistItems.insert` | 50 | Add video |
| `playlistItems.update` | 50 | Reorder video |
| `playlistItems.delete` | 50 | Remove video |
| `videos.list` | 1 | Metadata retrieval |
| `search.list` | **100** | Avoid when possible |

**Daily limit**: 10,000 units per project, resets at midnight Pacific Time.

## Optimization 1: Batch ID Requests

The `id` parameter accepts comma-separated values (up to 50). This provides 98% savings:

```python
# INEFFICIENT: 50 units for 50 videos
for vid_id in video_ids:
    youtube.videos().list(part='snippet', id=vid_id).execute()

# EFFICIENT: 1 unit for 50 videos
youtube.videos().list(
    part='snippet',
    id=','.join(video_ids[:50])
).execute()
```

### Implementation

Add batching helper to `api.py`:

```python
def batch_video_metadata(client: Resource, video_ids: list[str]) -> list[dict]:
    """Fetch video metadata in batches of 50.

    Args:
        client: YouTube API client
        video_ids: List of video IDs

    Returns:
        List of video metadata dicts

    Cost: ceil(len(video_ids) / 50) units
    """
    results = []
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i:i+50]
        response = client.videos().list(
            part='snippet,contentDetails,status',
            id=','.join(batch)
        ).execute()
        results.extend(response.get('items', []))
        record_quota('videos.list')
    return results
```

## Optimization 2: ETag Conditional Requests

YouTube API responses include ETags for caching. Use `If-None-Match` headers:

```python
from googleapiclient.errors import HttpError

def get_playlist_cached(client: Resource, playlist_id: str, cache: dict) -> dict:
    """Get playlist with ETag-based caching.

    A 304 Not Modified response still costs 1 unit but confirms cache validity
    without re-transferring the payload.
    """
    cached = cache.get(playlist_id)

    request = client.playlists().list(
        part='snippet,contentDetails',
        id=playlist_id
    )

    if cached and 'etag' in cached:
        # Add If-None-Match header
        request.headers['If-None-Match'] = cached['etag']

    try:
        response = request.execute()
        # Cache the response with its ETag
        cache[playlist_id] = {
            'data': response,
            'etag': response.get('etag'),
            'timestamp': time.time()
        }
        return response
    except HttpError as e:
        if e.resp.status == 304:
            # Not modified, return cached version
            return cached['data']
        raise
```

### ETag Cache Storage

Extend `cache.py` to store ETags:

```sql
-- Add etag column to existing tables
ALTER TABLE playlists ADD COLUMN etag TEXT;
ALTER TABLE videos ADD COLUMN etag TEXT;
```

## Optimization 3: Maximize Page Size

Always use `maxResults=50` (the maximum) for paginated endpoints:

```python
# Default is only 5 results - wasteful!
# Always specify maxResults=50
response = client.playlistItems().list(
    part='snippet',
    playlistId=playlist_id,
    maxResults=50,  # ALWAYS SET THIS
    pageToken=page_token
).execute()
```

### Pagination Impact

| Playlist Size | maxResults=5 | maxResults=50 |
|---------------|--------------|---------------|
| 100 videos | 20 API calls | **2 API calls** |
| 500 videos | 100 API calls | **10 API calls** |
| 1000 videos | 200 API calls | **20 API calls** |

## Optimization 4: Fields Parameter

Request only needed fields to reduce response size (doesn't reduce quota but improves performance):

```python
# Full response (larger payload)
response = client.videos().list(
    part='snippet,contentDetails,status,statistics',
    id=video_id
).execute()

# Minimal response (smaller payload)
response = client.videos().list(
    part='snippet',
    id=video_id,
    fields='items(id,snippet(title,channelTitle))'
).execute()
```

## Optimization 5: Avoid search.list

`search.list` costs 100 units per request - the most expensive operation. Never use it for bulk operations:

```python
# NEVER DO THIS for bulk operations (100 units per video!)
for title in video_titles:
    results = client.search().list(q=title, type='video').execute()

# INSTEAD: Use yt-dlp or direct video IDs
# yt-dlp can search by URL/title without quota
```

## Optimization 6: Pre-flight Quota Check

Before expensive operations, calculate required quota and warn users:

```python
def estimate_copy_cost(num_playlists: int, total_videos: int) -> QuotaEstimate:
    """Estimate quota cost before operation."""
    return QuotaEstimate(
        playlist_creates=num_playlists,
        video_adds=total_videos,
    )

# Before starting operation
estimate = estimate_copy_cost(5, 500)
if estimate.total > remaining_quota:
    console.print(f"[yellow]Warning: This operation requires {estimate.total} units")
    console.print(f"[yellow]You have {remaining_quota} units remaining")
    console.print(f"[yellow]Operation will require ~{estimate.days_required} days to complete")
```

## Implementation Checklist

- [ ] Add `batch_video_metadata()` to api.py
- [ ] Add ETag support to cache.py schema
- [ ] Implement ETag caching for playlist reads
- [ ] Audit all API calls for `maxResults=50`
- [ ] Remove or deprecate any `search.list` usage
- [ ] Add pre-flight quota estimation to batch commands
- [ ] Update QuotaEstimate to account for batching
