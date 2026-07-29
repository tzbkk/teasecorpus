# Provenance (ob Integration)

## Overview

teasecorpus implements record-level provenance tracking for each ChatML QA through [originblame](../rust-originblame), supporting:

- **Source Query**: `ob blame` — Query which wiki contributors a QA comes from
- **Author Revoke**: `ob revoke --email` — Mark all contributions from an author
- **Physical Purge**: `ob purge` — Delete revoked records (optional --dry-run for preview)

**Design Goal**: If a contributor's content needs to be removed in the future (e.g., copyright disputes), it can be precisely tracked and all derivative QAs can be batch deleted without affecting other valid records.

## Architecture

```
output/
├── .ob/
│   ├── authors/               # 23 unique contributors (铁桶 appears in both ns0 and 译名表 sections)
│   ├── sections/              # 24 sections: ns0 × 23 + 译名表 × 1
│   ├── document-index/        # line_hash + source mapping for each QA
│   └── teasecorpus_section_map.json  # cache: {(source, contributor): section_hash}
├── .cache/
│   └── {type}.jsonl           # Intermediate products (.gitignore)
└── dataset.jsonl              # Final dataset
```

### Sections Definition

| source_path | contributors | section count | purpose |
|-------------|--------------|--------------|---------|
| `wikidump/ns0.xml` | 23 (21 users + 2 IPs) | 23 | QA main source (all 7 pipelines) |
| `wikidump/擅长捉弄的高木同学wiki.xml::漫画标题译名表` | 铁桶 | 1 | Translation table QAs for chapter_qa |

Each `(source_path, contributor)` combination is registered as a section, and section_hash is used for `track(source=[hashes])`.

## Setup Process

### One-time Initialization

```bash
python src/setup_ob.py
```

This script performs the following steps:

1. **Parse ns0.xml contributors**:
   - Extract all `<revision>` elements from each page
   - Aggregate all timestamps for each contributor
   - Build `{contributor: (wiki_id, year_range_str)}` mapping

2. **Cherry-pick translation table**:
   - Extract the `漫画标题译名表` page from `wikidump/擅长捉弄的高木同学wiki.xml`
   - Parse contributors for that page (only 铁桶)

3. **Register authors + sections**:
   - Call `author_add(name=username, email={wiki_id}@teasecorpus.invalid)`
   - Call `register_section(path=source_path, authors=[name], year=year_range)`

4. **Cache section_map**:
   - Save to `.ob/teasecorpus_section_map.json`
   - Format: `[{"source": "...", "contributor": "...", "hash": "..."}, ...]`

**Expected Output**:
```
ns0.xml: 23 unique contributors
  铁桶: id=32416701 email=32416701@teasecorpus.invalid year='2018-2026'
  Lunisha Kumina: id=55584564 email=55584564@teasecorpus.invalid year='2024-2026'
  ...
译名表: 铁桶 id=32416701 email=32416701@teasecorpus.invalid year='2019-2026'
registered 24 sections
  - ns0.xml: 23
  - 译名表: 1
```

### Author Email Design

Email format: `{wiki_id}@teasecorpus.invalid`

- **wiki_id**: Fandom global stable identifier (`<id>` field), IP contributors use IP itself
- **`.invalid` TLD**: RFC 6761 reserved domain, guarantees NXDOMAIN (undeliverable)
- **Purpose**: Unique lookup key for `ob revoke --email`

Examples:
- 铁桶: `32416701@teasecorpus.invalid`
- IP contributor: `1.2.3.4@teasecorpus.invalid`

### Year Range Field

Format: `"YYYY"` or `"YYYY-YYYY"`

- Single-year contribution: `"2020"`
- Multi-year contribution: `"2018-2026"`
- Empty: `""`

Calculated by the `year_range(timestamps)` function, which extracts and deduplicates years from all revision timestamps.

Examples:
```
(ns0.xml, 铁桶)        -> "2018-2026" (spans 9 years)
(ns0.xml, Tugiacat666) -> "2020" (single year)
(译名表, 铁桶)          -> "2019-2026"
```

## Section Coverage Strategy

### ns0.xml (23 sections)

Covers all 408 pages in the ns0 namespace, including:

- 247 chapters
- 14 characters
- 37 episodes
- 41 music entries
- 23 volumes
- 3 seasons
- 1 movie
- 22 unclassified

All 23 contributors (21 users + 2 IPs) have contributions in ns0.xml.

### Translation Table (1 section)

Cherry-pick the `漫画标题译名表` page from `擅长捉弄的高木同学wiki.xml`, contributed by only 铁桶.

**Why cherry-pick?**
- Translation table provides Japanese/Chinese/English translated titles for chapters, an incremental data source for chapter_qa
- Other ns=4 pages (community rules, meta-templates, etc.) have no incremental value for QAs, verified by spike testing

## Page-level Attribution

We choose **page-level attribution** (rather than ob_util's chunk-level):

- **Granularity**: All contributors of each page are merged into one source set
- **Section count**: 24 sections (23 ns0 + 1 translation table)
- **Trade-off**: Simpler, but typographical fixers have equal rights with main authors

**Why not chunk-level?**
- chunk-level uses git-diff-style blame to attribute each line to the last modifier
- QA-level provenance doesn't need line-level precision
- chunk-level would result in a huge number of sections (each chunk × each contributor)

If line-level precision is needed in the future, can migrate to ob_util chunk-level mode.

## Pipeline Integration Pattern

**File parameter when tracking**: Fixed to `dataset.jsonl` (constant), not intermediate file paths. Rust blame ignores file when looking up by hash, but ob show displays the file field in records, using the final path is clearer.

**line_hash stability**: merge uses byte-level concatenation without changing content, line_hash remains consistent from pipeline → dataset.jsonl, `ob blame -d output/ output/dataset.jsonl N` can be used directly.

### 1. chapter_qa.py (Custom Mode)

**Feature**: Translation QAs need to include translation table section (铁桶)

```python
# Custom source_extractor
def _extract(item, qa_pair=None):
    contributors = item.get('contributors', set())
    hashes = [
        section_map[(NS0_PATH, c)]
        for c in contributors
        if (NS0_PATH, c) in section_map
    ]
    chap_id = item.get('infobox', {}).get('章节数目', '')
    if chap_id and chap_id in translation_table:
        # Has translation → append translation table section
        for (src, _contributor), h in section_map.items():
            if src == TRANSLATION_TABLE_PATH:
                hashes.append(h)
    return hashes

source_extractor = _extract
track_fn = track_chatml
```

### 2. character/episode/season/movie_qa.py (Standard Mode)

Use `make_source_extractor` helper function:

```python
source_extractor = make_source_extractor(
    section_map,
    source_path='wikidump/ns0.xml',
)
track_fn = track_chatml
```

### 3. music/volume_qa.py (Manual Mode)

Template-only, doesn't go through `run_pipeline`, directly calls `track_chatml` in inner loop:

```python
with open(data_path, 'a', encoding='utf-8') as f_out:
    for item in items:
        qa_pairs = template_qa_for_volume(item)
        for q, a in qa_pairs:
            chatml = to_chatml(system, q, a)
            f_out.write(json.dumps(chatml, ensure_ascii=False) + '\n')
            # Manual tracking
            if track_fn:
                source_hashes = source_extractor(item, (q, a))
                if source_hashes:
                    track_chatml(chatml, data_path, source_hashes)
```

### run_pipeline Parameters

```python
run_pipeline(
    items, build_prompt, build_template_qa, decontextualize,
    system, output_subdir, delay, max_items, item_id_fn,
    source_extractor=None,  # (item, qa_pair) -> list[section_hash] | None
    track_fn=None,          # (chatml, file_path, section_hashes) -> None
)
```

**Workflow**:
1. After each QA is written to JSONL, call `source_extractor(item, (q, a))`
2. If non-empty list is returned, call `track_fn(chatml, data_path, section_hashes)`
3. Track failures are recorded to `.errors.json`, doesn't block pipeline

## PID File Lifecycle

### Writing

`track()` writes temporary PID file: `.ob/docidx.{pid}`

- Each `track()` call appends an entry (`(line_hash, file, sources)` triple)
- Both JSONL and PID files are flushed at item rhythm (fsync JSONL after item completion)

### Merge

`clean_ob()` merges all PID files into manifest shards:

- **Called at startup**: Absorb PID files left from previous crash
- **Called at completion**: Ensure queries are immediately available
- **Idempotency**: No-op if no PID files exist

After merge_outputs.py runs, all records' file fields point to `dataset.jsonl`, can `ob blame` directly on the final product.

### Query Timing

Must wait until after `clean_ob()` to `ob blame` / `ob show`:

```
pipeline runs → track() writes PID → clean_ob() merge → ob blame available
```

### Conflict Prevention

Each pipeline startup and completion both call `clean_ob()`:

- At startup: Clean up leftovers from previous crash
- At completion: Ensure this run's data is immediately queryable

PID file conflicts will silently lose data, must follow this workflow.

## Query/Revoke

### ob blame — Query source of a QA

```bash
ob blame -d output/ output/dataset.jsonl 1
```

Outputs all section contributors for that QA.

### ob show — Query all records of an author

```bash
ob show -d output/ --email "32416701@teasecorpus.invalid"
```

Shows all QA records for 铁桶 (default excludes revoked, add `--revoked` to show revoked ones).

### ob revoke — Revoke author (toggle)

```bash
ob revoke -d output/ --email "32416701@teasecorpus.invalid"
```

Marks 铁桶 author.revoked=True, lazily cascades to all related sections + QA records.

- **Toggle mode**: Calling again revokes revoke (`--reverse` to restore)
- **Lazy cascade**: Write side only tags, queries automatically filter

### ob purge — Physical Delete

```bash
ob purge -d output/ output/dataset.jsonl --dry-run  # Preview
ob purge -d output/ output/dataset.jsonl            # Execute
```

Physically delete revoked records from JSONL file.

**Notes**:
- Must `ob revoke` before `ob purge`
- `--dry-run` to preview, prevent accidental deletion
- Recommend `ob purge` before re-running pipeline to clean old records

### ob status — Statistics

```bash
ob status -d output/
```

Shows:
- Number of authors
- Number of sections
- Number of manifest entries

## Troubleshooting

### "ob provenance: DISABLED (...)"

**Cause**: `setup_ob.py` not run or ob package not importable

**Solution**:
```bash
python src/setup_ob.py  # Register sections
python -c "from ob import init, track; from ob.api import _NATIVE; print(f'OK _NATIVE={_NATIVE}')"
```

### track fails into .errors.json

**Possible causes**:
- section_map cache outdated, need to rerun `setup_ob.py`
- PID file conflict, multiple pipelines running simultaneously
- ob package not correctly installed (`_NATIVE=False`)

**Solution**:
1. Check `.errors.json` content
2. Rerun `setup_ob.py` to update section_map
3. Ensure pipeline runs single-threaded

### `ob status` Authors count > 24

**Cause**: `author_add` called repeatedly (idempotent, harmless)

**Solution**: Ignore, doesn't affect functionality

### ob blame / ob show returns empty

**Cause**: `clean_ob()` not called to merge PID files

**Solution**:
```bash
ob clean -d output/  # Query available after merge
```

## HuggingFace Release

Release package contains three core files:

- `dataset.jsonl` — Final dataset, all QAs' line_hashes correspond to .ob/document-index/
- `README.md` — Dataset card, explaining data sources, usage, license
- `LICENSE` — License file

Users can download `dataset.jsonl` from HuggingFace Hub and query sources directly with `ob blame -d output/ output/dataset.jsonl N`.

## What's Not Integrated

The following features are not in teasecorpus integration scope:

### DEP-5 export

`ob export-copyright` can export copyright files, but doesn't enter pipeline workflow.

### Embedding reconcile

Dump is a static snapshot, doesn't need reconcile (only applicable to continuously updated datasets).

### Token-level tracking

QA-level provenance doesn't need tokenizer-level tracking.

### PII Stripping

Current implementation preserves `name` + `email` fields. Production deployment can strip PII per paper §6:

```bash
# Optional: Remove name/email from .ob/authors/, keep only SHA-256 id
```

### Source stack

Doesn't use `source.append/pop` pattern (thread-local per-file), instead uses explicit `track(source=[hashes])` to implement precise per-page contributor granularity.

## References

- [OriginBlame paper](https://arxiv.org/abs/2405.06332)
- [RFC 6761 — Reserved Top Level DNS Names](https://www.rfc-editor.org/rfc/rfc6761)
- [RFC 6762 — Multicast DNS](https://www.rfc-editor.org/rfc/rfc6762) (why not use .local)
