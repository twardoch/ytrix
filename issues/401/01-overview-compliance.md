# Part 1: Overview & ToS Compliance

## Executive Summary

This specification defines improvements to ytrix for ethical, compliant, and efficient YouTube Data API usage. The guiding principle: **effectiveness is measured by sustainable operation over months, not throughput per second**.

## Critical ToS Finding

**Multi-project quota rotation for a single application is explicitly forbidden by Google.**

From YouTube API Services Developer Policies (Section III.D.1.c):
> "You can't create multiple apps/sites or create multiple Google Cloud projects for use across multiple apps/sites to artificially acquire more quota (aka 'sharding') for a single API service or use case."

From Terms of Service (Section 15):
> "You and your API Client(s) will not, and will not attempt to, exceed or circumvent use or quota restrictions."

**Enforcement is active.** Users report receiving emails stating: "We have recently detected that your Google Cloud Project has been circumventing our quota restrictions via multiple projects that act as one." Consequences include quota reduction, API key revocation, and account termination.

## Legitimate Multi-Project Use Cases

The following are **compliant** reasons to maintain multiple GCP projects:

| Use Case | Example | Compliant? |
|----------|---------|------------|
| Environment isolation | dev / staging / prod | Yes |
| Platform separation | iOS app / Android app / web | Yes |
| Multi-tenancy | Agency managing Client A / Client B | Yes |
| Resilience/backup | Primary / failover (not for throughput) | Grey area |
| Quota circumvention | Round-robin to multiply quota | **No - Violation** |

## Architectural Pivot Required

The current ytrix implementation has `rotate_on_quota_exceeded()` which automatically cycles through projects when quota is exhausted. This behavior, if used to multiply quota for a single use case, violates ToS.

**Required Changes:**

1. **Rename "rotation" to "context switching"** - Emphasize selection of appropriate identity, not evasion
2. **Add `quota_group` field** - Projects must be grouped by purpose (personal, client-a, client-b)
3. **Restrict automatic switching** - Only within same quota_group, and only for legitimate failover
4. **Add prominent warnings** - Educate users about ToS boundaries
5. **Focus optimization efforts** - On batching, caching, and yt-dlp reads instead of multi-project rotation

## Success Metrics

| Metric | Target |
|--------|--------|
| API calls per playlist copy | Reduce by 50% through batching |
| Read operations using quota | 0% (all reads via yt-dlp) |
| ToS compliance | 100% (no quota circumvention features) |
| Setup time for new project | < 10 minutes with guidance |
| User understanding of quota | Clear dashboard showing usage/reset |

## Implementation Priority

1. **High**: Hybrid read/write architecture (yt-dlp for reads)
2. **High**: ToS-compliant project context management
3. **High**: Enhanced error handling (429 vs 403 distinction)
4. **Medium**: GCP setup automation improvements
5. **Medium**: CLI quota dashboard
6. **Low**: Multi-user futureproofing
