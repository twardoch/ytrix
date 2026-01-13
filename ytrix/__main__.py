"""ytrix CLI - YouTube playlist management."""

import json
from collections import defaultdict
from importlib import resources
from pathlib import Path
from typing import Any

import fire
from rich.console import Console
from rich.progress import Progress

from ytrix import __version__, api, cache, extractor, yaml_ops
from ytrix.config import get_config_dir, load_config
from ytrix.dedup import MatchType, analyze_batch_deduplication, load_target_playlists_with_videos
from ytrix.journal import (
    Journal,
    TaskStatus,
    clear_journal,
    create_journal,
    get_journal_summary,
    get_pending_tasks,
    load_journal,
    update_task,
)
from ytrix.logging import configure_logging, logger
from ytrix.models import Playlist, extract_playlist_id
from ytrix.quota import QuotaEstimate, format_quota_warning

console = Console()


class YtrixCLI:
    """YouTube playlist management CLI.

    Examples:
        ytrix plist2mlist "https://youtube.com/playlist?list=PLxxx"
        ytrix --verbose mlists2yaml --details
        ytrix --json-output plist2mlist PLxxx
        ytrix --throttle 500 plists2mlists playlists.txt  # Slower API calls
    """

    def __init__(
        self, verbose: bool = False, json_output: bool = False, throttle: int = 200
    ) -> None:
        """Initialize CLI with options.

        Args:
            verbose: Enable debug logging
            json_output: Output results as JSON instead of human-readable text
            throttle: Milliseconds between API write calls (default 200, 0 to disable)
        """
        configure_logging(verbose)
        self._json = json_output
        # Set API throttle delay
        api.set_throttle_delay(throttle)
        logger.debug(
            "ytrix initialized with verbose={}, json={}, throttle={}ms",
            verbose,
            json_output,
            throttle,
        )

    def _output(self, data: dict[str, Any]) -> dict[str, Any] | None:
        """Output result as JSON or print nothing (human output already printed)."""
        if self._json:
            print(json.dumps(data, indent=2))
        return data if self._json else None

    def version(self) -> None:
        """Show ytrix version."""
        if self._json:
            self._output({"version": __version__})
        else:
            console.print(f"ytrix {__version__}")

    def config(self) -> dict[str, Any] | None:
        """Show configuration status and setup instructions.

        Displays:
            - Config file path
            - Current config (if exists)
            - Setup guide (if not configured)

        Example:
            ytrix config
        """
        config_dir = get_config_dir()
        config_path = config_dir / "config.toml"
        token_path = config_dir / "token.json"

        if self._json:
            result: dict[str, Any] = {
                "config_path": str(config_path),
                "config_exists": config_path.exists(),
                "token_path": str(token_path),
                "token_exists": token_path.exists(),
            }
            if config_path.exists():
                result["config_content"] = config_path.read_text()
            return self._output(result)

        console.print(f"[bold]Config path:[/bold] {config_path}")
        console.print(f"[bold]Token path:[/bold] {token_path}")
        console.print()

        if config_path.exists():
            console.print("[green]Config file exists[/green]")
            console.print()
            # Show content with secrets masked
            content = config_path.read_text()
            for line in content.strip().split("\n"):
                if "secret" in line.lower() and "=" in line:
                    key = line.split("=")[0]
                    console.print(f"  {key}= [dim]<hidden>[/dim]")
                else:
                    console.print(f"  {line}")
            console.print()
            if token_path.exists():
                console.print("[green]OAuth token cached (authorized)[/green]")
            else:
                console.print("[yellow]No OAuth token yet (run a command to authorize)[/yellow]")
        else:
            console.print("[red]Config file not found[/red]")
            console.print()
            console.print("[bold]Setup guide:[/bold]")
            console.print()
            # Read bundled SETUP.txt
            try:
                setup_text = resources.files("ytrix").joinpath("SETUP.txt").read_text()
                print(setup_text)  # Use print() to avoid Rich markup interpretation
            except Exception:
                console.print("  See: https://github.com/fontlabtv/ytrix for setup instructions")
        return None

    def cache_stats(self) -> dict[str, Any] | None:
        """Show cache statistics.

        Displays cache location, size, and entry counts.

        Example:
            ytrix cache_stats
            ytrix --json-output cache_stats
        """
        stats = cache.get_cache_stats()

        if self._json:
            return self._output(stats)

        console.print(f"[bold]Cache path:[/bold] {stats['path']}")
        if "size_mb" in stats:
            console.print(f"[bold]Cache size:[/bold] {stats['size_mb']} MB")
        console.print()

        for table in ["playlists", "videos", "playlist_videos", "channel_playlists"]:
            info = stats.get(table, {})
            console.print(f"  {table}: {info.get('valid', 0)} valid / {info.get('total', 0)} total")

        return None

    def cache_clear(self, expired_only: bool = False) -> dict[str, Any] | None:
        """Clear cached data.

        Args:
            expired_only: Only clear expired entries (default: clear all)

        Example:
            ytrix cache_clear              # Clear all cache
            ytrix cache_clear --expired-only  # Only clear expired entries
        """
        if expired_only:
            deleted = cache.clear_expired()
            msg = f"Cleared {deleted} expired cache entries"
        else:
            deleted = cache.clear_cache()
            msg = f"Cleared {deleted} cache entries"

        if self._json:
            return self._output({"deleted": deleted, "expired_only": expired_only})

        console.print(f"[green]{msg}[/green]")
        return None

    def journal_status(
        self, clear: bool = False, pending_only: bool = False
    ) -> dict[str, Any] | None:
        """Show batch operation journal status.

        Displays the current batch operation journal, including task counts by status
        and details of incomplete tasks. Use --clear to delete the journal.

        Args:
            clear: Delete the journal file
            pending_only: Show only pending and failed tasks (tasks that need work)

        Example:
            ytrix journal_status               # Show journal status
            ytrix journal_status --clear       # Clear the journal
            ytrix journal_status --pending-only # Show only incomplete tasks
            ytrix --json-output journal_status
        """
        if clear:
            clear_journal()
            msg = "Journal cleared"
            if self._json:
                return self._output({"cleared": True})
            console.print(f"[green]{msg}[/green]")
            return None

        journal = load_journal()
        if journal is None:
            if self._json:
                return self._output({"exists": False})
            console.print("[yellow]No journal found[/yellow]")
            return None

        summary = get_journal_summary(journal)

        # Filter tasks if pending_only
        if pending_only:
            filtered_tasks = [
                t
                for t in journal.tasks
                if t.status in (TaskStatus.PENDING, TaskStatus.FAILED, TaskStatus.IN_PROGRESS)
            ]
        else:
            filtered_tasks = journal.tasks

        if self._json:
            tasks_data = [t.to_dict() for t in filtered_tasks]
            return self._output(
                {
                    "batch_id": journal.batch_id,
                    "created_at": journal.created_at,
                    "summary": summary,
                    "tasks": tasks_data,
                    "pending_only": pending_only,
                }
            )

        console.print(f"[bold]Batch:[/bold] {journal.batch_id}")
        console.print(f"[bold]Created:[/bold] {journal.created_at}")
        console.print()
        console.print("[bold]Summary:[/bold]")
        console.print(f"  Total: {summary['total']}")
        console.print(f"  [green]Completed: {summary['completed']}[/green]")
        console.print(f"  [blue]Skipped: {summary['skipped']}[/blue]")
        console.print(f"  [yellow]Pending: {summary['pending']}[/yellow]")
        console.print(f"  [red]Failed: {summary['failed']}[/red]")

        # Show failed tasks with errors
        failed = [t for t in filtered_tasks if t.status == TaskStatus.FAILED]
        if failed:
            console.print()
            console.print("[bold red]Failed tasks:[/bold red]")
            for t in failed:
                console.print(f"  {t.source_title}")
                console.print(f"    [dim]Error: {t.error}[/dim]")
                console.print(f"    [dim]Retries: {t.retry_count}[/dim]")

        # Show pending tasks if pending_only
        if pending_only:
            pending = [t for t in filtered_tasks if t.status == TaskStatus.PENDING]
            if pending:
                console.print()
                console.print("[bold yellow]Pending tasks:[/bold yellow]")
                for t in pending:
                    console.print(f"  {t.source_title}")

        return None

    def ls(
        self, count: bool = False, user: str | None = None, urls: bool = False
    ) -> dict[str, Any] | None:
        """List playlists.

        Args:
            count: Show video count for each playlist (slower, requires extra API calls)
            user: Channel URL, @handle, or channel ID to list playlists from (uses yt-dlp)
            urls: Output only playlist URLs, one per line (for piping to plists2mlist)

        Example:
            ytrix ls                          # List your playlists
            ytrix ls --count                  # Include video counts
            ytrix ls --user @fontlabtv        # List another channel's playlists
            ytrix ls --user @fontlabtv --urls # URLs only, pipe to file
            ytrix --json-output ls
        """
        # List another user's playlists via yt-dlp
        if user:
            if not self._json and not urls:
                console.print(f"[blue]Fetching playlists from {user}...[/blue]")

            playlists = extractor.extract_channel_playlists(user)

            # URLs-only output for piping to plists2mlist
            if urls:
                for p in playlists:
                    print(f"https://youtube.com/playlist?list={p.id}")
                return None

            # Fetch video counts if requested (uses yt-dlp, no API quota)
            video_counts: dict[str, int] = {}
            if count and playlists:
                if not self._json:
                    console.print("[blue]Fetching video counts...[/blue]")
                for p in playlists:
                    video_counts[p.id] = extractor.get_video_count(p.id)

            if self._json:
                playlist_data = []
                for p in playlists:
                    entry: dict[str, Any] = {"id": p.id, "title": p.title, "privacy": p.privacy}
                    if count:
                        entry["video_count"] = video_counts.get(p.id, 0)
                    playlist_data.append(entry)
                return self._output({"count": len(playlists), "playlists": playlist_data})

            if not playlists:
                console.print("[yellow]No playlists found[/yellow]")
                return None

            console.print(f"Found {len(playlists)} playlists:\n")
            for p in playlists:
                count_tag = f" ({video_counts[p.id]} videos)" if count else ""
                console.print(f"  {p.title}{count_tag}")
                console.print(f"    [dim]https://youtube.com/playlist?list={p.id}[/dim]")
            return None

        # List own playlists via YouTube API
        config = load_config()
        client = api.get_youtube_client(config)

        if not self._json and not urls:
            console.print("[blue]Fetching playlists...[/blue]")

        playlists = api.list_my_playlists(client, config.channel_id)

        # URLs-only output for piping to plists2mlist
        if urls:
            for p in playlists:
                print(f"https://youtube.com/playlist?list={p.id}")
            return None

        # Fetch video counts if requested (uses yt-dlp to avoid API quota)
        video_counts: dict[str, int] = {}
        if count and playlists:
            if not self._json:
                console.print("[blue]Fetching video counts...[/blue]")
            for p in playlists:
                try:
                    # Try yt-dlp first (no API quota)
                    video_counts[p.id] = extractor.get_video_count(p.id)
                except Exception:
                    # Fall back to API for private playlists
                    videos = api.get_playlist_videos(client, p.id)
                    video_counts[p.id] = len(videos)

        if self._json:
            playlist_data = []
            for p in playlists:
                entry: dict[str, Any] = {"id": p.id, "title": p.title, "privacy": p.privacy}
                if count:
                    entry["video_count"] = video_counts.get(p.id, 0)
                playlist_data.append(entry)
            return self._output({"count": len(playlists), "playlists": playlist_data})

        if not playlists:
            console.print("[yellow]No playlists found[/yellow]")
            return None

        console.print(f"Found {len(playlists)} playlists:\n")
        for p in playlists:
            privacy_tag = f" \\[{p.privacy}]" if p.privacy != "public" else ""
            count_tag = f" ({video_counts[p.id]} videos)" if count else ""
            console.print(f"  {p.title}{privacy_tag}{count_tag}")
            console.print(f"    [dim]https://youtube.com/playlist?list={p.id}[/dim]")

        return None

    def plist2mlist(
        self,
        url_or_id: str,
        dry_run: bool = False,
        dedup: bool = True,
        title: str | None = None,
        privacy: str = "public",
    ) -> str | dict[str, Any] | None:
        """Copy external playlist to your channel.

        Args:
            url_or_id: Playlist URL or ID to copy
            dry_run: Show what would be created without making changes
            dedup: Check for existing duplicates before creating (default: True)
            title: Custom title for the new playlist (default: use source title)
            privacy: Privacy setting: public, unlisted, or private (default: public)

        Example:
            ytrix plist2mlist "https://youtube.com/playlist?list=PLxxx"
            ytrix plist2mlist PLxxx --dry-run
            ytrix plist2mlist PLxxx --no-dedup
            ytrix plist2mlist PLxxx --title "My Copy"
            ytrix plist2mlist PLxxx --privacy unlisted
        """
        if privacy not in ("public", "unlisted", "private"):
            raise ValueError("--privacy must be 'public', 'unlisted', or 'private'")
        from ytrix.dedup import MatchType, find_matching_playlist

        logger.debug("plist2mlist called with url_or_id={}, dedup={}", url_or_id, dedup)

        if not self._json:
            console.print("[blue]Extracting playlist...[/blue]")
        source = extractor.extract_playlist(url_or_id)
        logger.debug("Extracted playlist: {} with {} videos", source.title, len(source.videos))

        if not self._json:
            console.print(f"Found: {source.title} ({len(source.videos)} videos)")

        config = load_config()

        # Deduplication check
        match_result = None
        if dedup and not dry_run:
            if not self._json:
                console.print("[blue]Checking for duplicates...[/blue]")
            target_playlists = load_target_playlists_with_videos(config.channel_id)
            if target_playlists:
                match_result = find_matching_playlist(source, target_playlists)

                if match_result.match_type == MatchType.EXACT:
                    target = match_result.target_playlist
                    assert target is not None  # guaranteed by EXACT match
                    url = f"https://www.youtube.com/playlist?list={target.id}"
                    if not self._json:
                        console.print(f"[green]Exact match found: {target.title}[/green]")
                        console.print(f"[green]Skipping - existing playlist: {url}[/green]")
                        return url
                    return self._output(
                        {
                            "action": "skipped",
                            "reason": "exact_match",
                            "existing_playlist_id": target.id,
                            "existing_playlist_title": target.title,
                            "url": url,
                        }
                    )

                if match_result.match_type == MatchType.PARTIAL:
                    target = match_result.target_playlist
                    assert target is not None  # guaranteed by PARTIAL match
                    missing = match_result.missing_videos or []
                    if not self._json:
                        pct = match_result.overlap_percent * 100
                        msg = f"[yellow]Partial match ({pct:.0f}%): {target.title}[/yellow]"
                        console.print(msg)
                        console.print(f"[yellow]Adding {len(missing)} missing videos...[/yellow]")

        if dry_run:
            playlist_title = title or source.title
            result: dict[str, Any] = {
                "dry_run": True,
                "title": playlist_title,
                "privacy": privacy,
                "description": source.description,
                "video_count": len(source.videos),
                "videos": [{"id": v.id, "title": v.title} for v in source.videos],
            }
            if match_result:
                result["dedup"] = {
                    "match_type": match_result.match_type.value,
                    "overlap_percent": match_result.overlap_percent,
                }
                if match_result.target_playlist:
                    result["dedup"]["target_playlist_id"] = match_result.target_playlist.id
            if self._json:
                return self._output(result)
            console.print("[yellow]Dry run - would create:[/yellow]")
            console.print(f"  Title: {playlist_title}")
            console.print(f"  Privacy: {privacy}")
            console.print(f"  Videos: {len(source.videos)}")
            for v in source.videos[:5]:
                console.print(f"    - {v.title[:50]}")
            if len(source.videos) > 5:
                console.print(f"    ... and {len(source.videos) - 5} more")
            return None

        client = api.get_youtube_client(config)

        # Handle partial match - add missing videos to existing playlist
        if match_result and match_result.match_type == MatchType.PARTIAL:
            target = match_result.target_playlist
            assert target is not None  # guaranteed by PARTIAL match
            missing_ids = set(match_result.missing_videos or [])
            videos_to_add = [v for v in source.videos if v.id in missing_ids]

            added = 0
            skipped = []
            if self._json:
                for video in videos_to_add:
                    try:
                        api.add_video_to_playlist(client, target.id, video.id)
                        added += 1
                    except Exception as e:
                        skipped.append({"id": video.id, "error": str(e)})
            else:
                with Progress(console=console) as progress:
                    task = progress.add_task("Adding videos...", total=len(videos_to_add))
                    for video in videos_to_add:
                        try:
                            api.add_video_to_playlist(client, target.id, video.id)
                            added += 1
                        except Exception as e:
                            skipped.append({"id": video.id, "error": str(e)})
                            console.print(f"[yellow]Skipped {video.id}: {e}[/yellow]")
                        progress.advance(task)

            url = f"https://www.youtube.com/playlist?list={target.id}"
            if not self._json:
                console.print(f"[green]Updated: {url}[/green]")
                return url

            return self._output(
                {
                    "action": "updated",
                    "playlist_id": target.id,
                    "url": url,
                    "title": target.title,
                    "videos_added": added,
                    "videos_skipped": skipped,
                }
            )

        # No match - create new playlist
        playlist_title = title or source.title
        if not self._json:
            console.print("[blue]Creating playlist on your channel...[/blue]")

        new_id = api.create_playlist(client, playlist_title, source.description, privacy)
        logger.debug("Created playlist with id={}", new_id)

        added = 0
        skipped = []
        if self._json:
            for video in source.videos:
                try:
                    api.add_video_to_playlist(client, new_id, video.id)
                    added += 1
                except Exception as e:
                    skipped.append({"id": video.id, "error": str(e)})
        else:
            with Progress(console=console) as progress:
                task = progress.add_task("Adding videos...", total=len(source.videos))
                for video in source.videos:
                    try:
                        api.add_video_to_playlist(client, new_id, video.id)
                        added += 1
                    except Exception as e:
                        skipped.append({"id": video.id, "error": str(e)})
                        console.print(f"[yellow]Skipped {video.id}: {e}[/yellow]")
                    progress.advance(task)

        url = f"https://www.youtube.com/playlist?list={new_id}"
        if not self._json:
            console.print(f"[green]Created: {url}[/green]")
            return url

        return self._output(
            {
                "playlist_id": new_id,
                "url": url,
                "title": playlist_title,
                "privacy": privacy,
                "videos_added": added,
                "videos_skipped": skipped,
            }
        )

    def plists2mlist(
        self,
        file_path: str,
        title: str | None = None,
        dry_run: bool = False,
        privacy: str = "public",
    ) -> str | dict[str, Any] | None:
        """Merge multiple playlists into one on your channel.

        Args:
            file_path: Text file with playlist URLs/IDs (one per line)
            title: Optional title for the merged playlist
            dry_run: Show what would be created without making changes
            privacy: Privacy setting: public, unlisted, or private (default: public)

        Example:
            ytrix plists2mlist playlists.txt
            ytrix plists2mlist playlists.txt --title "My Collection"
            ytrix plists2mlist playlists.txt --privacy unlisted
        """
        if privacy not in ("public", "unlisted", "private"):
            raise ValueError("--privacy must be 'public', 'unlisted', or 'private'")
        # Read playlist URLs/IDs from file
        lines = Path(file_path).read_text().strip().split("\n")
        lines = [line.strip() for line in lines if line.strip() and not line.startswith("#")]
        if not lines:
            raise ValueError("No playlist URLs found in file")

        if not self._json:
            console.print(f"[blue]Processing {len(lines)} playlists...[/blue]")

        all_videos = []
        source_playlists = []
        for line in lines:
            try:
                playlist = extractor.extract_playlist(line)
                if not self._json:
                    console.print(f"  {playlist.title}: {len(playlist.videos)} videos")
                source_playlists.append(
                    {"title": playlist.title, "video_count": len(playlist.videos)}
                )
                all_videos.extend(playlist.videos)
            except Exception as e:
                if not self._json:
                    console.print(f"[yellow]Skipped {line}: {e}[/yellow]")

        if not all_videos:
            raise ValueError("No videos found in any playlist")

        # Detect duplicates
        seen_ids: set[str] = set()
        duplicates: list[str] = []
        unique_videos = []
        for video in all_videos:
            if video.id in seen_ids:
                duplicates.append(video.id)
            else:
                seen_ids.add(video.id)
                unique_videos.append(video)

        if duplicates and not self._json:
            console.print(f"[yellow]Found {len(duplicates)} duplicate videos (skipped)[/yellow]")

        playlist_title = title or f"Merged Playlist ({len(unique_videos)} videos)"

        if dry_run:
            if self._json:
                return self._output(
                    {
                        "dry_run": True,
                        "title": playlist_title,
                        "privacy": privacy,
                        "source_playlists": source_playlists,
                        "unique_videos": len(unique_videos),
                        "duplicates_skipped": len(duplicates),
                    }
                )
            console.print("[yellow]Dry run - would create:[/yellow]")
            console.print(f"  Title: {playlist_title}")
            console.print(f"  Privacy: {privacy}")
            console.print(f"  Unique videos: {len(unique_videos)}")
            if duplicates:
                console.print(f"  Duplicates skipped: {len(duplicates)}")
            console.print(f"  From {len(source_playlists)} playlists")
            return None

        config = load_config()
        client = api.get_youtube_client(config)

        if not self._json:
            console.print(f"[blue]Creating merged playlist: {playlist_title}[/blue]")
        new_id = api.create_playlist(client, playlist_title, privacy=privacy)

        added = 0
        if self._json:
            for video in unique_videos:
                try:
                    api.add_video_to_playlist(client, new_id, video.id)
                    added += 1
                except Exception:
                    pass
        else:
            with Progress(console=console) as progress:
                task = progress.add_task("Adding videos...", total=len(unique_videos))
                for video in unique_videos:
                    try:
                        api.add_video_to_playlist(client, new_id, video.id)
                        added += 1
                    except Exception as e:
                        console.print(f"[yellow]Skipped {video.id}: {e}[/yellow]")
                    progress.advance(task)

        url = f"https://www.youtube.com/playlist?list={new_id}"
        if not self._json:
            console.print(f"[green]Created: {url}[/green]")
            return url

        return self._output(
            {
                "playlist_id": new_id,
                "url": url,
                "title": playlist_title,
                "privacy": privacy,
                "videos_added": added,
                "duplicates_skipped": len(duplicates),
            }
        )

    def plist2mlists(
        self, url_or_id: str, by: str = "channel", dry_run: bool = False
    ) -> list[str] | dict[str, Any] | None:
        """Split playlist into sub-playlists by criterion.

        Args:
            url_or_id: Playlist URL or ID to split
            by: Criterion to split by ('channel' or 'year')
            dry_run: Show what would be created without making changes

        Example:
            ytrix plist2mlists PLxxx --by=channel
            ytrix plist2mlists PLxxx --by=year --dry-run
        """
        if by not in ("channel", "year"):
            raise ValueError("--by must be 'channel' or 'year'")

        if not self._json:
            console.print("[blue]Extracting playlist...[/blue]")
        source = extractor.extract_playlist(url_or_id)
        if not self._json:
            console.print(f"Found: {source.title} ({len(source.videos)} videos)")

        # Group videos by criterion
        groups: dict[str, list[Any]] = defaultdict(list)
        for video in source.videos:
            if by == "channel":
                key = video.channel or "Unknown Channel"
            else:  # year
                key = video.upload_date[:4] if video.upload_date else "Unknown Year"
            groups[key].append(video)

        # Preview mode
        if dry_run:
            planned = [
                {"title": f"{source.title} - {name}", "group": name, "video_count": len(vids)}
                for name, vids in groups.items()
            ]
            if self._json:
                return self._output(
                    {
                        "dry_run": True,
                        "source_title": source.title,
                        "split_by": by,
                        "playlists_planned": len(planned),
                        "playlists": planned,
                    }
                )
            console.print("[yellow]Dry run - would create:[/yellow]")
            for p in planned:
                console.print(f"  {p['title']}: {p['video_count']} videos")
            return None

        config = load_config()
        client = api.get_youtube_client(config)

        if not self._json:
            console.print(f"[blue]Creating {len(groups)} playlists...[/blue]")

        created_playlists: list[dict[str, Any]] = []

        for group_name, videos in groups.items():
            title = f"{source.title} - {group_name}"
            if not self._json:
                console.print(f"  {title}: {len(videos)} videos")

            new_id = api.create_playlist(client, title, source.description)

            added = 0
            for video in videos:
                try:
                    api.add_video_to_playlist(client, new_id, video.id)
                    added += 1
                except Exception as e:
                    if not self._json:
                        console.print(f"[yellow]Skipped {video.id}: {e}[/yellow]")

            url = f"https://www.youtube.com/playlist?list={new_id}"
            created_playlists.append(
                {
                    "playlist_id": new_id,
                    "url": url,
                    "title": title,
                    "group": group_name,
                    "videos_added": added,
                }
            )
            if not self._json:
                console.print(f"[green]Created: {url}[/green]")

        if self._json:
            return self._output(
                {
                    "source_title": source.title,
                    "split_by": by,
                    "playlists_created": len(created_playlists),
                    "playlists": created_playlists,
                }
            )

        return [p["url"] for p in created_playlists]

    def plists2mlists(
        self, file_path: str, dry_run: bool = False, resume: bool = False
    ) -> dict[str, Any] | None:
        """Batch copy playlists one-to-one with deduplication and journaling.

        Copies each source playlist to a separate playlist on your channel.
        Handles API quota limits gracefully - use --resume to continue after quota resets.

        Features:
            - Skips playlists that already exist with identical videos
            - Updates existing playlists if >75% videos match
            - Journals progress for resume across sessions
            - Retries failed operations with exponential backoff

        Args:
            file_path: Text file with playlist URLs/IDs (one per line)
            dry_run: Preview operations without making changes
            resume: Continue from previous journal (for quota limit recovery)

        Example:
            ytrix plists2mlists playlists.txt --dry-run
            ytrix plists2mlists playlists.txt
            ytrix plists2mlists playlists.txt --resume  # After quota resets
        """
        config = load_config()

        # Check for existing journal if resuming
        journal: Journal | None = None
        if resume:
            journal = load_journal()
            if journal:
                summary = get_journal_summary(journal)
                if not self._json:
                    console.print(f"[blue]Resuming batch: {journal.batch_id}[/blue]")
                    console.print(
                        f"  Completed: {summary['completed']}, "
                        f"Pending: {summary['pending']}, "
                        f"Failed: {summary['failed']}"
                    )
            else:
                if not self._json:
                    console.print("[yellow]No journal found, starting fresh[/yellow]")

        # Read source playlists from file if not resuming with existing journal
        if not journal:
            lines = Path(file_path).read_text().strip().split("\n")
            lines = [line.strip() for line in lines if line.strip() and not line.startswith("#")]
            if not lines:
                raise ValueError("No playlist URLs found in file")

            if not self._json:
                console.print(f"[blue]Extracting {len(lines)} source playlists...[/blue]")

            source_playlists = []
            for line in lines:
                try:
                    playlist = extractor.extract_playlist(line)
                    source_playlists.append(playlist)
                    if not self._json:
                        console.print(f"  {playlist.title}: {len(playlist.videos)} videos")
                except Exception as e:
                    if not self._json:
                        console.print(f"[yellow]Skipped {line}: {e}[/yellow]")

            if not source_playlists:
                raise ValueError("No valid playlists found")

            # Create journal for new batch
            journal = create_journal([(p.id, p.title) for p in source_playlists])

            # Load target channel playlists for deduplication (uses yt-dlp, no quota)
            if not self._json:
                console.print("[blue]Loading target channel playlists for deduplication...[/blue]")
            target_playlists = load_target_playlists_with_videos(config.channel_id)

            # Analyze deduplication
            dedup_results = analyze_batch_deduplication(source_playlists, target_playlists)

            # Update journal with deduplication results
            for source in source_playlists:
                result = dedup_results.get(source.id)
                if result:
                    if result.match_type == MatchType.EXACT:
                        target_id = result.target_playlist.id if result.target_playlist else None
                        update_task(
                            journal,
                            source.id,
                            status=TaskStatus.SKIPPED,
                            match_type="exact",
                            match_playlist_id=target_id,
                        )
                    elif result.match_type == MatchType.PARTIAL:
                        target_id = result.target_playlist.id if result.target_playlist else None
                        update_task(
                            journal,
                            source.id,
                            match_type="partial",
                            match_playlist_id=target_id,
                        )
        else:
            # Resuming - reload source playlists for pending tasks
            source_playlists = []
            for task in get_pending_tasks(journal):
                try:
                    playlist = extractor.extract_playlist(task.source_playlist_id)
                    source_playlists.append(playlist)
                except Exception as e:
                    logger.warning("Failed to reload {}: {}", task.source_playlist_id, e)

        # Calculate quota estimate
        pending_tasks = get_pending_tasks(journal)
        pending_ids = {t.source_playlist_id for t in pending_tasks}
        total_videos = sum(len(p.videos) for p in source_playlists if p.id in pending_ids)
        estimate = QuotaEstimate(
            playlist_creates=len([t for t in pending_tasks if t.match_type != "partial"]),
            video_adds=total_videos,
            playlist_updates=len([t for t in pending_tasks if t.match_type == "partial"]),
        )

        if not self._json:
            console.print()
            console.print(format_quota_warning(estimate))
            console.print()

        if dry_run:
            summary = get_journal_summary(journal)
            if self._json:
                return self._output(
                    {
                        "dry_run": True,
                        "batch_id": journal.batch_id,
                        "summary": summary,
                        "quota_estimate": estimate.breakdown(),
                        "tasks": [t.to_dict() for t in journal.tasks],
                    }
                )
            console.print("[yellow]Dry run - no changes made[/yellow]")
            console.print(f"  Would create: {summary['pending']} playlists")
            console.print(f"  Will skip: {summary['skipped']} (already exist)")
            return None

        # Execute batch operations
        client = api.get_youtube_client(config)
        source_by_id = {p.id: p for p in source_playlists}

        for task in pending_tasks:
            source = source_by_id.get(task.source_playlist_id)
            if not source:
                continue

            update_task(journal, task.source_playlist_id, status=TaskStatus.IN_PROGRESS)

            try:
                if task.match_type == "partial" and task.match_playlist_id:
                    # Update existing playlist - add missing videos
                    if not self._json:
                        console.print(f"[blue]Updating: {source.title}[/blue]")
                    target_id = task.match_playlist_id
                    existing_ids = extractor.get_playlist_video_ids(target_id)
                    added = 0
                    for video in source.videos:
                        if video.id not in existing_ids:
                            try:
                                api.add_video_to_playlist(client, target_id, video.id)
                                added += 1
                            except Exception as e:
                                logger.warning("Failed to add {}: {}", video.id, e)
                    update_task(
                        journal,
                        task.source_playlist_id,
                        status=TaskStatus.COMPLETED,
                        target_playlist_id=target_id,
                        videos_added=added,
                    )
                    if not self._json:
                        console.print(
                            f"[green]Updated: https://youtube.com/playlist?list={target_id} "
                            f"(+{added} videos)[/green]"
                        )
                else:
                    # Create new playlist
                    if not self._json:
                        console.print(f"[blue]Creating: {source.title}[/blue]")
                    new_id = api.create_playlist(client, source.title, source.description)

                    added = 0
                    with Progress(console=console, disable=self._json) as progress:
                        prog_task = progress.add_task("Adding videos...", total=len(source.videos))
                        for video in source.videos:
                            try:
                                api.add_video_to_playlist(client, new_id, video.id)
                                added += 1
                            except Exception as e:
                                logger.warning("Failed to add {}: {}", video.id, e)
                            progress.advance(prog_task)

                    update_task(
                        journal,
                        task.source_playlist_id,
                        status=TaskStatus.COMPLETED,
                        target_playlist_id=new_id,
                        videos_added=added,
                    )
                    if not self._json:
                        console.print(
                            f"[green]Created: https://youtube.com/playlist?list={new_id}[/green]"
                        )

            except Exception as e:
                logger.error("Failed {}: {}", task.source_playlist_id, e)
                update_task(
                    journal,
                    task.source_playlist_id,
                    status=TaskStatus.FAILED,
                    error=str(e),
                    increment_retry=True,
                )
                if not self._json:
                    console.print(f"[red]Failed: {source.title} - {e}[/red]")
                    console.print("[yellow]Use --resume to retry after quota resets[/yellow]")

        # Final summary
        summary = get_journal_summary(journal)
        if summary["pending"] == 0 and summary["failed"] == 0:
            clear_journal()
            if not self._json:
                console.print("[green]Batch complete![/green]")
        else:
            if not self._json:
                console.print(
                    f"[yellow]Batch incomplete: {summary['pending']} pending, "
                    f"{summary['failed']} failed[/yellow]"
                )
                console.print("Use --resume to continue after quota resets at midnight PT")

        if self._json:
            return self._output(
                {
                    "batch_id": journal.batch_id,
                    "summary": summary,
                    "tasks": [t.to_dict() for t in journal.tasks],
                }
            )
        return None

    def mlists2yaml(
        self, output: str = "playlists.yaml", details: bool = False
    ) -> str | dict[str, Any] | None:
        """Export all your playlists to YAML.

        Args:
            output: Output file path
            details: Include video details in export

        Example:
            ytrix mlists2yaml
            ytrix mlists2yaml --output my_playlists.yaml --details
        """
        config = load_config()
        client = api.get_youtube_client(config)

        if not self._json:
            console.print("[blue]Fetching playlists...[/blue]")
        playlists = api.list_my_playlists(client, config.channel_id)
        if not self._json:
            console.print(f"Found {len(playlists)} playlists")

        if details:
            # Use yt-dlp to avoid API quota, fall back to API for private playlists
            if self._json:
                for playlist in playlists:
                    try:
                        extracted = extractor.extract_playlist(playlist.id)
                        playlist.videos = extracted.videos
                    except Exception:
                        playlist.videos = api.get_playlist_videos(client, playlist.id)
            else:
                with Progress(console=console) as progress:
                    task = progress.add_task("Fetching video details...", total=len(playlists))
                    for playlist in playlists:
                        try:
                            extracted = extractor.extract_playlist(playlist.id)
                            playlist.videos = extracted.videos
                        except Exception:
                            playlist.videos = api.get_playlist_videos(client, playlist.id)
                        progress.advance(task)

        # With --json-output, print JSON and skip file
        if self._json:
            return self._output(
                {
                    "playlists": [p.to_dict(include_videos=details) for p in playlists],
                    "count": len(playlists),
                }
            )

        yaml_ops.save_yaml(output, playlists, include_videos=details)
        console.print(f"[green]Saved to: {output}[/green]")
        return output

    def yaml2mlists(self, file_path: str, dry_run: bool = False) -> dict[str, Any] | None:
        """Apply YAML edits to your playlists.

        Args:
            file_path: YAML file with playlist data
            dry_run: Show changes without applying

        Example:
            ytrix yaml2mlists playlists.yaml --dry-run
            ytrix yaml2mlists playlists.yaml
        """
        config = load_config()
        client = api.get_youtube_client(config)

        new_playlists = yaml_ops.load_yaml(file_path)
        if not self._json:
            console.print(f"[blue]Processing {len(new_playlists)} playlists...[/blue]")

        results: list[dict[str, Any]] = []

        for new_pl in new_playlists:
            try:
                # Get current state
                current = api.get_playlist_with_videos(client, new_pl.id)
                changes = yaml_ops.diff_playlists(current, new_pl)

                result: dict[str, Any] = {
                    "playlist_id": new_pl.id,
                    "title": new_pl.title,
                    "changes": changes,
                    "applied": False,
                }

                if not changes:
                    if not self._json:
                        console.print(f"  {new_pl.title}: no changes")
                    results.append(result)
                    continue

                if not self._json:
                    console.print(f"  {new_pl.title}:")
                    for key, val in changes.items():
                        console.print(f"    {key}: {val}")

                if dry_run:
                    results.append(result)
                    continue

                # Apply metadata changes
                if any(k in changes for k in ("title", "description", "privacy")):
                    api.update_playlist(
                        client,
                        new_pl.id,
                        title=new_pl.title if "title" in changes else None,
                        description=new_pl.description if "description" in changes else None,
                        privacy=new_pl.privacy if "privacy" in changes else None,
                    )

                # Handle video removals
                if "videos_removed" in changes:
                    items = api.get_playlist_items(client, new_pl.id)
                    item_by_video = {item.video_id: item for item in items}
                    for vid_id in changes["videos_removed"]:
                        if vid_id in item_by_video:
                            api.remove_video_from_playlist(client, item_by_video[vid_id].item_id)
                            logger.debug("Removed video {}", vid_id)

                # Handle video additions
                if "videos_added" in changes:
                    for vid_id in changes["videos_added"]:
                        try:
                            api.add_video_to_playlist(client, new_pl.id, vid_id)
                            logger.debug("Added video {}", vid_id)
                        except Exception as e:
                            logger.warning("Failed to add video {}: {}", vid_id, e)

                # Handle reordering (after adds/removes)
                if "videos_reordered" in changes and new_pl.videos:
                    new_order = [v.id for v in new_pl.videos]
                    api.reorder_playlist_videos(client, new_pl.id, new_order)
                    logger.debug("Reordered playlist videos")

                result["applied"] = True
                results.append(result)

            except Exception as e:
                if not self._json:
                    console.print(f"[red]Error processing {new_pl.id}: {e}[/red]")
                results.append(
                    {
                        "playlist_id": new_pl.id,
                        "title": new_pl.title,
                        "error": str(e),
                    }
                )

        if self._json:
            return self._output(
                {
                    "dry_run": dry_run,
                    "playlists_processed": len(results),
                    "playlists": results,
                }
            )

        if dry_run:
            console.print("[yellow]Dry run - no changes applied[/yellow]")
        else:
            console.print("[green]Done[/green]")
        return None

    def mlist2yaml(self, url_or_id: str, output: str | None = None) -> str | dict[str, Any] | None:
        """Export single playlist to YAML.

        Args:
            url_or_id: Playlist URL or ID (must be on your channel)
            output: Output file path

        Example:
            ytrix mlist2yaml PLxxx
            ytrix mlist2yaml PLxxx --output mylist.yaml
        """
        config = load_config()
        client = api.get_youtube_client(config)

        playlist_id = extract_playlist_id(url_or_id)

        # Get playlist metadata from API (need privacy status)
        response = client.playlists().list(part="snippet,status", id=playlist_id).execute()
        if not response["items"]:
            raise ValueError(f"Playlist not found: {playlist_id}")
        item = response["items"][0]

        # Try yt-dlp for videos (no API quota), fall back to API for private playlists
        try:
            extracted = extractor.extract_playlist(playlist_id)
            videos = extracted.videos
        except Exception:
            videos = api.get_playlist_videos(client, playlist_id)

        playlist = Playlist(
            id=playlist_id,
            title=item["snippet"]["title"],
            description=item["snippet"].get("description", ""),
            privacy=item["status"]["privacyStatus"],
            videos=videos,
        )

        if self._json:
            return self._output({"playlist": playlist.to_dict(include_videos=True)})

        out_path = output or f"playlist_{playlist_id}.yaml"
        yaml_ops.save_yaml(out_path, [playlist])

        console.print(f"[green]Saved to: {out_path}[/green]")
        return out_path

    def yaml2mlist(self, file_path: str, dry_run: bool = False) -> dict[str, Any] | None:
        """Apply YAML edits to single playlist.

        Args:
            file_path: YAML file with playlist data
            dry_run: Show changes without applying

        Example:
            ytrix yaml2mlist mylist.yaml --dry-run
            ytrix --json-output yaml2mlist mylist.yaml
        """
        # Reuse yaml2mlists since it handles single playlists too
        return self.yaml2mlists(file_path, dry_run=dry_run)


def main() -> None:
    """CLI entry point."""
    fire.Fire(YtrixCLI)


if __name__ == "__main__":
    main()
