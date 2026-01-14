# YouTube API quota management: what works within Google's rules

**Multi-project quota rotation for a single application is explicitly forbidden.** Google's Developer Policies prohibit "sharding"—creating multiple GCP projects to artificially acquire more quota for one API service or use case. Violations can result in quota reduction, API key revocation, or Google account termination. However, the **10,000 daily units** allocation can stretch significantly further through compliant optimization strategies: aggressive caching, request batching, and using yt-dlp for read operations can reduce API calls by **90% or more**. For genuinely high-volume needs, quota increases are free and typically approved within 3-5 business days through Google's compliance audit process.

## Understanding the YouTube Data API v3 quota system

The YouTube Data API v3 allocates **10,000 units per day per Google Cloud project**, resetting at **midnight Pacific Time**. Different operations carry vastly different costs—a critical factor for the ytrix CLI tool's design.

| Operation | Quota Cost | Notes |
|-----------|------------|-------|
| `playlists.list` | 1 | Batch up to 50 IDs per request |
| `playlistItems.list` | 1 | Use maxResults=50 |
| `playlists.insert` | 50 | Creating new playlist |
| `playlists.update` | 50 | Modifying existing |
| `playlists.delete` | 50 | Removing playlist |
| `playlistItems.insert` | 50 | Adding video to playlist |
| `playlistItems.update` | 50 | Modifying item |
| `playlistItems.delete` | 50 | Removing video |
| `videos.list` | 1 | Metadata retrieval |
| `search.list` | **100** | Avoid when possible |

A playlist manager operating within the default quota can perform approximately **200 write operations** or **10,000 read operations** daily. The `search.list` endpoint at 100 units per call depletes quota rapidly—prefer `videos.list` with known video IDs whenever possible. As of December 2025, video upload costs dropped from ~1,600 to ~100 units, though this doesn't affect playlist management.

Quota tracking is available in the **GCP Console** under APIs & Services → YouTube Data API v3 → Quotas tab, showing per-method breakdown and historical usage. Cloud Monitoring can trigger alerts when `quota/exceeded` metrics spike.

## Why multi-project "sharding" violates Terms of Service

Google's Developer Policies explicitly address and prohibit quota circumvention through multiple projects:

> "**You can't create multiple apps/sites or create multiple Google Cloud projects for use across multiple apps/sites to artificially acquire more API quota (aka 'sharding') for a single API service or use case.**"
> — YouTube API Services Developer Policies Guide, Section III.D.1.c

The Terms of Service (Section 15) reinforce this: "**You and your API Client(s) will not, and will not attempt to, exceed or circumvent use or quota restrictions.**"

Google actively monitors for sharding. Users on GitHub have reported receiving enforcement emails stating: "We have recently detected that your Google Cloud Project has been circumventing our quota restrictions via multiple projects that act as one." Consequences include immediate quota reduction, API key revocation, and potential Google account termination.

**Legitimately separate projects are permitted** for distinct environments (development, staging, production), different platforms (iOS app vs. Android app vs. web), or genuinely separate use cases (user-facing features vs. internal analytics). A CLI tool like ytrix accessing a single user's playlists constitutes one use case requiring one project.

## Compliant quota optimization strategies

Since credential rotation across multiple projects is off-limits, optimization must focus on maximizing value from each API call.

**Batch video IDs in single requests.** The `id` parameter accepts comma-separated values (up to 50). Requesting metadata for 50 videos costs **1 unit total**, not 50—a 98% savings. This pattern applies to `videos.list`, `playlists.list`, and `channels.list`:

```python
# EFFICIENT: 1 unit for 50 videos
response = youtube.videos().list(
    part='snippet,status',
    id='vid1,vid2,vid3,...,vid50'  # Up to 50 IDs
).execute()

# WASTEFUL: 50 units for 50 separate calls
for vid_id in video_ids:
    youtube.videos().list(part='snippet', id=vid_id).execute()
```

**Implement aggressive caching with ETags.** YouTube API responses include ETags for conditional requests. Cache responses locally with their ETags, then send subsequent requests with `If-None-Match` headers. A **304 Not Modified** response still costs 1 unit but confirms cached data remains valid without re-transferring the full payload:

```python
from googleapiclient.errors import HttpError

def get_playlist_cached(youtube, playlist_id, cache):
    cached = cache.get(playlist_id)
    headers = {'If-None-Match': cached['etag']} if cached else {}
    
    try:
        response = youtube.playlists().list(
            part='snippet,contentDetails',
            id=playlist_id
        ).execute(http=http_with_headers(headers))
        cache[playlist_id] = {'data': response, 'etag': response['etag']}
        return response
    except HttpError as e:
        if e.resp.status == 304:
            return cached['data']  # Use cached version
        raise
```

**Always use `maxResults=50`** for paginated endpoints. Default is 5 results—maximizing page size reduces pagination calls by 90%.

**Use the `fields` parameter** to request only needed data, reducing response size and processing overhead (though not quota cost directly).

## Using yt-dlp for read operations without quota

The yt-dlp library extracts YouTube metadata through web scraping, consuming **zero API quota**. This provides an effective fallback for read-only operations like fetching playlist contents or video metadata.

```python
from yt_dlp import YoutubeDL

def get_playlist_videos_no_quota(playlist_id):
    """Fetch playlist contents without API quota."""
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': True,  # Metadata only, no download
        'skip_download': True,
    }
    url = f'https://youtube.com/playlist?list={playlist_id}'
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        return [
            {'video_id': entry['id'], 'title': entry['title']}
            for entry in info.get('entries', [])
        ]
```

yt-dlp can retrieve video titles, descriptions, durations, view counts, channel information, and thumbnail URLs. **Caveats**: Heavy usage risks IP-based rate limiting; add `--sleep-interval 3` for bulk operations. Age-restricted content may require browser cookies. Write operations (creating playlists, adding videos) still require the official API.

**Recommended hybrid approach**: Use yt-dlp for initial playlist reads and periodic syncs; reserve API quota for write operations and data the scraper can't access reliably.

## GCP project setup and OAuth configuration

For the single project ytrix should use, setup requires enabling the API and configuring OAuth correctly.

**gcloud CLI commands**:
```bash
# Create project
gcloud projects create ytrix-prod --name="ytrix Playlist Manager"

# Enable YouTube API
gcloud services enable youtube.googleapis.com --project=ytrix-prod

# List enabled services (verify)
gcloud services list --enabled --project=ytrix-prod
```

**Terraform configuration**:
```hcl
resource "google_project" "ytrix" {
  name       = "ytrix Playlist Manager"
  project_id = "ytrix-prod"
}

resource "google_project_service" "youtube_api" {
  project = google_project.ytrix.project_id
  service = "youtube.googleapis.com"
  disable_on_destroy = false
}
```

**Critical OAuth constraint**: YouTube Data API **does not support service accounts** for user data operations. Playlist management requires OAuth 2.0 user consent—service account credentials return `NoLinkedYouTubeAccount` errors. The required scope is `https://www.googleapis.com/auth/youtube.force-ssl` for read/write playlist operations, or `youtube.readonly` for read-only access.

OAuth consent screen configuration requires app name, support email, and developer contact. External apps accessing YouTube's sensitive scopes require Google verification (2-4 weeks), though development testing with up to 100 designated test users can proceed without verification.

## Token management for CLI tools

Robust token handling ensures ytrix maintains authenticated sessions across invocations:

```python
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
import os

SCOPES = ['https://www.googleapis.com/auth/youtube.force-ssl']
TOKEN_PATH = os.path.expanduser('~/.config/ytrix/token.json')
CLIENT_SECRETS = os.path.expanduser('~/.config/ytrix/client_secrets.json')

def get_youtube_client():
    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())  # Automatic token refresh
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                CLIENT_SECRETS, SCOPES,
                autogenerate_code_verifier=True  # Enable PKCE
            )
            creds = flow.run_local_server(
                host='127.0.0.1',
                port=0,  # Auto-select available port
                success_message='Authentication complete. Return to ytrix.'
            )
        
        # Save with restrictive permissions
        os.makedirs(os.path.dirname(TOKEN_PATH), exist_ok=True)
        with open(TOKEN_PATH, 'w') as f:
            f.write(creds.to_json())
        os.chmod(TOKEN_PATH, 0o600)
    
    return build('youtube', 'v3', credentials=creds)
```

Access tokens expire after ~1 hour; the google-api-python-client automatically refreshes them using the stored refresh token. Refresh tokens persist indefinitely unless the user revokes access at myaccount.google.com/permissions or Google enforces limits (multiple refresh tokens per client).

**Security best practices**: Store tokens in `~/.config/ytrix/` with **0o600 permissions**. Never commit credentials to version control. Use `127.0.0.1` for localhost redirect (some systems have firewall issues with `localhost`). Enable PKCE via `autogenerate_code_verifier=True` for enhanced security.

## Error handling and exponential backoff

When quota is exhausted, YouTube returns HTTP **403** with reason `quotaExceeded`. Proper error handling distinguishes quota exhaustion from rate limits:

```python
import time
import random
from googleapiclient.errors import HttpError

def execute_with_backoff(request_func, max_retries=5):
    """Execute API request with exponential backoff for transient errors."""
    for attempt in range(max_retries):
        try:
            return request_func()
        except HttpError as e:
            error_reason = e.error_details[0].get('reason', '') if e.error_details else ''
            
            if error_reason == 'quotaExceeded':
                # Don't retry—quota won't reset until midnight PT
                raise QuotaExhaustedError(
                    "Daily quota exhausted. Resets at midnight Pacific Time."
                )
            
            if error_reason in ('rateLimitExceeded', 'backendError'):
                # Transient error—exponential backoff with jitter
                if attempt < max_retries - 1:
                    delay = min(2 ** attempt, 32) + random.uniform(0, 1)
                    time.sleep(delay)
                    continue
            
            raise  # Non-retryable error
    
    raise MaxRetriesExceededError("Request failed after maximum retries")
```

**Retryable errors**: `rateLimitExceeded`, `backendError`, `internalError` (use backoff). **Non-retryable**: `quotaExceeded`, `forbidden`, `notFound`, `badRequest` (fail immediately with informative message).

## Quota state persistence across CLI sessions

Track quota consumption locally to predict remaining capacity and warn users before exhaustion:

```python
import sqlite3
from datetime import datetime
import pytz

class QuotaTracker:
    def __init__(self, db_path='~/.config/ytrix/quota.db'):
        self.db_path = os.path.expanduser(db_path)
        self._init_db()
        self.daily_limit = 10000
    
    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute('''
            CREATE TABLE IF NOT EXISTS quota_usage (
                date TEXT PRIMARY KEY,
                units_used INTEGER DEFAULT 0,
                last_updated TEXT
            )
        ''')
        conn.commit()
        conn.close()
    
    def _get_pacific_date(self):
        pacific = pytz.timezone('US/Pacific')
        return datetime.now(pacific).strftime('%Y-%m-%d')
    
    def record_usage(self, units):
        today = self._get_pacific_date()
        conn = sqlite3.connect(self.db_path)
        conn.execute('''
            INSERT INTO quota_usage (date, units_used, last_updated)
            VALUES (?, ?, datetime('now'))
            ON CONFLICT(date) DO UPDATE SET
                units_used = units_used + ?,
                last_updated = datetime('now')
        ''', (today, units, units))
        conn.commit()
        conn.close()
    
    def get_remaining(self):
        today = self._get_pacific_date()
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            'SELECT units_used FROM quota_usage WHERE date = ?', (today,)
        ).fetchone()
        conn.close()
        used = row[0] if row else 0
        return self.daily_limit - used
```

Display warnings when quota drops below thresholds (e.g., 20% remaining), and refuse operations when estimated cost exceeds remaining quota.

## CLI dashboard patterns with Rich library

Rich provides flicker-free live-updating displays ideal for quota monitoring:

```python
from rich.live import Live
from rich.table import Table
from rich.panel import Panel
from rich.layout import Layout
from rich.console import Console

def create_quota_display(tracker):
    remaining = tracker.get_remaining()
    percentage = (remaining / 10000) * 100
    
    table = Table(title="ytrix Quota Status")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right")
    
    table.add_row("Daily Limit", "10,000 units")
    table.add_row("Used Today", f"{10000 - remaining:,} units")
    table.add_row("Remaining", f"{remaining:,} units")
    table.add_row("Usage", f"{100 - percentage:.1f}%")
    
    # Calculate time until reset
    pacific = pytz.timezone('US/Pacific')
    now = datetime.now(pacific)
    midnight = now.replace(hour=0, minute=0, second=0) + timedelta(days=1)
    hours_until = (midnight - now).seconds // 3600
    table.add_row("Reset In", f"~{hours_until} hours")
    
    return table

# Live updating display
with Live(create_quota_display(tracker), refresh_per_second=1) as live:
    for operation in operations:
        execute_operation(operation)
        live.update(create_quota_display(tracker))
```

For complex dashboards, Rich's `Layout` system supports multi-panel displays showing quota status alongside operation logs and progress bars.

## Requesting a quota increase through official channels

For legitimately high-volume use cases, Google's quota increase process is **free** and typically processes within **3-5 business days**.

**Submit via**: [YouTube API Services - Audit and Quota Extension Form](https://support.google.com/youtube/contact/yt_api_form)

**Required information**:
- Google Cloud Project ID and number
- OAuth Client ID
- Application URL or link to where the API client is used
- Clear, specific use case description ("Playlist management CLI for content creators managing 50+ playlists" not "video app")
- Current and requested quota levels with justification
- Monthly active users or demonstrable user base
- Privacy policy URL and data retention practices

**Success factors**: Specific use case with measurable scale, evidence of responsible API usage (caching, batching), explicit ToS compliance acknowledgment, and verified OAuth consent screen for production apps.

## Conclusion

Building a compliant, robust YouTube playlist CLI requires abandoning multi-project quota rotation—it's explicitly prohibited and actively enforced. Instead, **maximize efficiency through batching, caching, and yt-dlp for reads**, which can reduce API consumption by 90% or more. A single GCP project with careful quota tracking, appropriate error handling, and local persistence provides sufficient infrastructure for most playlist management use cases.

For ytrix specifically: implement comma-separated ID batching for all list operations, cache playlist contents with ETags refreshing hourly, use yt-dlp as the primary read mechanism (reserving API quota for writes), track quota in SQLite with Pacific Time awareness, and display real-time quota status via Rich. If the default 10,000 units proves insufficient despite optimization, request an increase through Google's free audit process—the compliant path scales indefinitely while ToS violations risk permanent API access loss.