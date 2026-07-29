# Dump Management

## Download Full Dump

```bash
python src/pipeline_preproc/download_dump.py
```

Full download of ns0(main) + ns4(project) namespaces, including complete revision history.

**Options**:

| Parameter | Description |
|-----------|-------------|
| `--ns 0 4` | Specify namespaces |
| `--force` | Force re-download (overwrite existing + progress) |
| `--list-only` | Only list page titles, do not download |
| `--delay 2.0` | Request interval in seconds (default 1.0) |

**Resumable download**: `.progress.json` records `last_completed_idx`, automatically resumes on rerun after interruption.

## Incremental Updates

```bash
python src/pipeline_preproc/update_dump.py
```

Download incremental revisions since the last full dump based on the `recentchanges` API.

**Artifacts**:

```
wikidump/ns0.delta.20250101-120000.xml      # Incremental XML
wikidump/ns0.deleted.20250101-120000.txt     # Deletion/move list (when events occur)
```

**Limitations**:
- Window: 30 days (warning if over 25 days)
- Does not modify original full dump files
- Merge back to full: manual or `download_dump.py --force`

## Data Profile (spike data)

| dump | ns | pages | purpose |
|------|-----|-------|---------|
| ns0.xml | 0 (main) | 408 | chapters/characters/episodes/music/volumes/seasons/movies |
| 擅长捉弄的高木同学wiki.xml | 4 (project) | 26 | translation table cherry-pick / community rule pages |

### ns0.xml Content Distribution

```
247 chapters + 14 characters + 37 episodes + 41 music + 23 volumes + 3 seasons + 1 movies
+ 22 unclassified (gallery/sandbox) = 408 pages

Contributors: 23 (21 users + 2 IPs)
铁桶: 2018-2026 (across all pages)
Lunisha Kumina: 2024-2026
```

Note: `setup_ob.py` extracts these contributor statistics from the dump to register ob sections. Each contributor's year_range is calculated from all revision timestamps for that page.