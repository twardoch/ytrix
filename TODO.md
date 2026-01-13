# ytrix TODO

## Phase 9: Multi-Project Credential Rotation - Remaining

### Core Features (Complete)
- [x] Multi-project config with `[[projects]]` array
- [x] Per-project token storage in ~/.ytrix/tokens/
- [x] Credential rotation via `projects.py` module
- [x] Quota tracking with daily reset
- [x] CLI commands: projects, projects_auth, projects_select

### Remaining Tasks
- [x] Add `--project` flag to force specific project on commands
- [x] Update SETUP.txt with multi-project setup guide
- [x] Update README with rotation documentation

### Future (Not Planned)
- [ ] `gcp_clone` and `gcp_inventory` CLI wrappers for gcptrix
- [ ] `projects_add` interactive project setup wizard
- [ ] Playlist description templates
- [ ] Watch later playlist support
- [ ] Playlist thumbnail management
