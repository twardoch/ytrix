---
title: Home
nav_order: 1
---

# ytrix

YouTube playlist management CLI. Copy playlists between channels, split by criteria (channel or year), and edit metadata via YAML — all using the YouTube Data API v3 with OAuth2 and multi-project quota rotation.

## Quick Start

```bash
pip install ytrix
ytrix config      # shows setup guide
ytrix ls          # list your playlists
```

## Features

- **Copy** external playlists to your channel (`plist2mlist`)
- **Merge** multiple playlists into one (`plists2mlist`)
- **Batch copy** playlists one-to-one (`plists2mlists`)
- **Split** a playlist by channel or year (`plist2mlists --by=channel|year`)
- **Export** playlists to YAML and apply edits back (`mlists2yaml` / `yaml2mlists`)
- **Extract** subtitles and transcripts (`plist2info`)
- **Multi-project** quota rotation for heavy usage
- **Resume** interrupted batch operations with `--resume`

## Links

- [GitHub](https://github.com/twardoch/ytrix)
- [PyPI](https://pypi.org/project/ytrix/)
- [Issues](https://github.com/twardoch/ytrix/issues)
