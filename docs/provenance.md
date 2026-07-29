# Provenance (ob Integration)

## Overview

teasecorpus implements record-level provenance tracking for every ChatML QA pair through [originblame](https://pypi.org/project/originblame/), enabling:

- **Source Query**: `ob blame` — list which wiki contributors a given QA derives from
- **Author Revoke**: `ob revoke --email` — soft-revoke all contributions from one author
- **Physical Purge**: `ob purge` — delete revoked records from the dataset (supports `--dry-run`)

**Design goal**: if a contributor's content ever needs removal (e.g., a copyright dispute), their derivative QAs can be located and batch-deleted precisely, without affecting other records.

## Architecture

```
output/                              # OB_DIR (the ob root)
├── .ob/
│   ├── authors/                     # 23 unique contributors (21 users + 2 IPs)
│   ├── sections/                    # 409 page-level sections
│   ├── document-index/              # line_hash + source mapping for each QA
│   └── teasecorpus_section_map.json # cache: {page_title -> section_hash}
├── .cache/
│   └── {type}.jsonl                 # intermediate artifacts (.gitignore)
└── dataset.jsonl                    # final merged dataset (the tracked file)
```

### Section model — one section per wiki page

The unit of attribution is the **wiki page**, not the contributor. Each page becomes exactly one section:

```
section_hash = SHA-256({ path, authors, license, year })
  path    = page title (unique within the wiki)
  authors = ALL contributors of that page, as one group
  license = "CC-BY-SA-3.0"
  year    = union year range of every revision on that page
```

This follows originblame's three-tier model (path / authors / license / year) at the coarsest meaningful granularity for QA-level provenance.

| source                                                                | pages | sections | contributors           |
|-----------------------------------------------------------------------|-------|----------|------------------------|
| `wikidump/ns0.xml`                                                    | 408   | 408      | 23 (21 users + 2 IPs)  |
| `wikidump/擅长捉弄的高木同学wiki.xml` (cherry-picked `译名表` page)   | 1     | 1        | 铁桶                   |
| **Total**                                                             | **409** | **409** | 23 unique              |

**Why page-level rather than chunk-level?**

- QA-level provenance doesn't need line-level precision.
- All contributors of a page are merged into one source set — simpler and stable across runs.
- Chunk-level (git-diff-style blame attributing each line to its last modifier) would explode section count (chunk × contributor) without value for downstream revoke.
- Trade-off: a typo fixer shares equal attribution with the main author of a page. Acceptable for a fan-wiki corpus.

### Section coverage

ns0.xml's 408 pages cover all 7 QA pipelines (chapter / character / episode / music / volume / season / movie) plus unclassified pages. The cherry-picked `擅长捉弄的高木同学wiki:漫画标题译名表` page provides Japanese/Chinese translated titles for `chapter_qa.py`. Other ns=4 pages (community rules, meta-templates, etc.) carry no QA-relevant signal and are deliberately excluded.

## Setup

### One-time initialization

```bash
python src/setup_ob.py
```

Pipeline (`src/setup_ob.py`):

1. **Parse ns0.xml** — `load_dump()` returns per-page contributor maps: `{page_title -> {contributor_name -> [timestamps]}}` and `{contributor_name -> wiki_id_or_ip}`.
2. **Cherry-pick `译名表`** — `load_cherry_pick_page()` extracts that single page from `擅长捉弄的高木同学wiki.xml` and merges its contributors into the same maps.
3. **`init_ob()`** — calls `ob.init(ob_dir=output)`.
4. **`register_all_pages()`** — for each page (sorted), register one section.
5. **`save_section_map()`** — write the `{page_title -> section_hash}` cache to `output/.ob/teasecorpus_section_map.json`.

### Per-page registration

`register_page_section(page_title, contributor_names, contributor_ids, year_str)`:

```python
for name in contributor_names:
    wid = contributor_ids.get(name, name)
    author_add(name=name, email=f'{wid}@teasecorpus.invalid', ob_dir=OB_DIR)
return register_section(
    path=page_title,
    authors=contributor_names,   # ALL contributors of this page, as a group
    license='CC-BY-SA-3.0',
    year=year_str,
    ob_dir=OB_DIR,
)
```

`register_all_pages()` aggregates every revision timestamp across all contributors on a page and passes the union year range to `year_range()`.

### Author email format

`{wiki_id}@teasecorpus.invalid`

- **`wiki_id`**: Fandom stable `<id>` for registered users; the raw IP string for anonymous editors.
- **`.invalid` TLD**: RFC 6761 reserved — guaranteed NXDOMAIN, undeliverable, unambiguous as a synthetic key.
- **Purpose**: stable lookup key for `ob revoke --email`.

Examples:

| contributor | wiki_id | email |
|-------------|---------|-------|
| 铁桶 (top contributor, 2018–2026) | 32416701 | `32416701@teasecorpus.invalid` |
| anonymous editor | `1.2.3.4` | `1.2.3.4@teasecorpus.invalid` |

### Year range field

`year_range(timestamps)` formats the union of all revision years on a page:

- single year → `"2020"`
- multi year  → `"2018-2026"`
- empty       → `""`

Because the year is computed across **all contributors on the page**, the same page-section year span reflects the page's full edit history (not any individual contributor's).

### section_map cache

On-disk format (`output/.ob/teasecorpus_section_map.json`, UTF-8, sorted by page title):

```json
[
  {"page": "<page_title>", "hash": "<sha256>"},
  ...
]
```

In-memory format returned by `load_section_map()` is `{page_title -> section_hash}`. If the cache is missing, `load_section_map()` raises `RuntimeError` instructing to run `setup_ob.py` — pipelines catch this and degrade to provenance-disabled mode.

## Pipeline Integration

All seven QA pipelines call into the same two helpers:

```python
source_extractor = make_source_extractor(section_map)        # standard
# or
source_extractor = make_chapter_source_extractor(section_map, translation_table)  # chapter only

track_fn = track_chatml
```

### `make_source_extractor(section_map)` — standard

Returns `(item, qa_pair=None) -> list[section_hash] | None`. Looks up `item['title']` in `section_map`. One section per page. Used by character / episode / music / volume / season / movie pipelines.

```python
def extract(item, qa_pair=None):
    title = item.get('title')
    if title and title in section_map:
        return [section_map[title]]
    return None
```

### `make_chapter_source_extractor(section_map, translation_table)` — chapter-specific

Returns the page section hash, **plus** the `译名表` page section hash when the chapter has an entry in the translation table. This is because translation-table data (jp / zh titles authored by 铁桶) is injected into the chapter prompt, so its derived QAs must trace back to both the chapter page **and** the translation-table page.

```python
def extract(item, qa_pair=None):
    hashes = []
    title = item.get('title')
    if title and title in section_map:
        hashes.append(section_map[title])               # chapter page section
    chap_id = item.get('infobox', {}).get('章节数目', '')
    if chap_id and chap_id in translation_table and tt_hash:
        hashes.append(tt_hash)                          # 译名表 page section
    return hashes if hashes else None
```

`tt_hash` is resolved once from `section_map[TRANSLATION_TABLE_TITLE]` where `TRANSLATION_TABLE_TITLE = '擅长捉弄的高木同学wiki:漫画标题译名表'`.

### `track_chatml(chatml, file_path, section_hashes)`

```python
track(chatml, file='dataset.jsonl', source=section_hashes, ob_dir=OB_DIR)
```

The `file_path` argument is **deliberately ignored** — tracking always records `file='dataset.jsonl'` (the `DATASET_PATH` constant). This way, after `merge_outputs.py` byte-concatenates the per-type caches into the final `output/dataset.jsonl`, `ob blame` resolves records directly against the final file. Intermediate per-type paths never appear in the document index.

### Pipeline bootstrap pattern

Every pipeline follows the same try/except pattern, so a missing section_map or unimportable `ob` package disables provenance without crashing generation:

```python
try:
    section_map = load_section_map()
    clean_ob()                                           # absorb crash leftovers
    source_extractor = make_source_extractor(section_map)
    track_fn = track_chatml
    print('>> ob provenance: ENABLED', flush=True)
except (RuntimeError, ImportError) as e:
    source_extractor = None
    track_fn = None
    print(f'>> ob provenance: DISABLED ({type(e).__name__}: {e})', flush=True)
```

After the pipeline completes, a final `clean_ob()` merges pending PID files so queries work immediately:

```python
if track_fn is not None:
    merged = clean_ob()
    print(f'>> ob clean: merged {merged} records', flush=True)
```

### `run_pipeline` contract

```python
run_pipeline(
    items, build_prompt, build_template_qa, decontextualize,
    system, output_subdir, delay, max_items, item_id_fn,
    source_extractor=None,   # (item, qa_pair) -> list[section_hash] | None
    track_fn=None,           # (chatml, file_path, section_hashes) -> None
)
```

For each generated QA pair: write the ChatML line to the per-type cache JSONL, then if `source_extractor(item, (q, a))` returns a non-empty list, call `track_fn(chatml, data_path, section_hashes)`. Track failures are logged to `.errors.json` and never block generation.

## PID File Lifecycle

### Write

`ob.track()` appends a `(line_hash, file, sources)` entry to a per-process PID file `output/.ob/docidx.{pid}`. Each pipeline flushes both the JSONL and the PID file at item granularity.

### Merge — `clean_ob()`

```python
from ob._ob_native import clean as _native_clean
result = _native_clean(str(OB_DIR), False)
return result.get('document_merged', 0) if isinstance(result, dict) else 0
```

`ob._ob_native` is the PyO3 native module shipped with the pip-installed `originblame` package. `clean_ob()` is called at two points:

- **pipeline start** — absorb PID files left over from a previous crash;
- **pipeline end** — make this run's records immediately queryable.

Idempotent: no-op when no PID files exist. Failing to call `clean_ob()` before querying is the most common cause of empty `ob blame` output.

### Query timing

```
pipeline runs  →  track() writes docidx.{pid}  →  clean_ob() merges  →  ob blame / ob show available
```

## Query / Revoke

All commands take `-d output/` to point at OB_DIR.

### `ob blame` — which contributors produced a QA

```bash
ob blame -d output/ output/dataset.jsonl 1
```

Lists every section (and its authors) backing line 1 of `dataset.jsonl`.

### `ob show` — all records by an author

```bash
ob show -d output/ --email "32416701@teasecorpus.invalid"
```

All QA records attributed to 铁桶. Revoked records are excluded by default; add `--revoked` to include them.

### `ob revoke` — soft-revoke an author (toggle)

```bash
ob revoke -d output/ --email "32416701@teasecorpus.invalid"
```

Marks the author's `revoked=True`; queries lazily filter revoked records. Calling again is a no-op toggle (`--reverse` restores). No data is physically removed.

### `ob purge` — physical delete

```bash
ob purge -d output/ output/dataset.jsonl --dry-run   # preview
ob purge -d output/ output/dataset.jsonl             # execute
```

Removes revoked records from the JSONL file.

- Must `ob revoke` first.
- Always preview with `--dry-run`.
- Recommended before re-running a pipeline, to drop stale records from prior runs.

### `ob status` — inventory

```bash
ob status -d output/
```

Reports author count, section count, and document-index entry count. Sections should read **409** after a clean `setup_ob.py`.

## Troubleshooting

### `>> ob provenance: DISABLED (...)`

Two usual causes:

1. `setup_ob.py` not run yet → `section_map` cache missing (`RuntimeError`).
2. `ob` not importable (`ImportError`) → re-check the install steps in the README:

```bash
python src/setup_ob.py
python -c "from ob import init, track; from ob.api import _NATIVE; print(f'ob OK _NATIVE={_NATIVE}')"
```

### Track failures in `.errors.json`

Inspect the file, then:

- section_map cache stale → re-run `setup_ob.py`;
- PID file conflict → ensure no two pipelines run concurrently against the same OB_DIR;
- native module not loaded (`_NATIVE=False`) → re-install originblame.

### `ob blame` / `ob show` returns empty despite tracked records

`clean_ob()` hasn't merged the PID files. Re-run any pipeline (which calls `clean_ob()` at start and end) or trigger a clean manually.

### `ob status` reports more authors than 23

`author_add` is idempotent and may be invoked across re-runs; harmless. The unique-author count is what matters.

## What's Not Integrated

- **DEP-5 / `ob export-copyright`** — available in ob but not part of the pipeline workflow.
- **Embedding reconcile** — the dump is a static snapshot; reconcile is only meaningful for continuously updated corpora.
- **Token-level tracking** — QA-level provenance doesn't require tokenizer granularity.
- **PII stripping** — `name` + `email` are currently retained verbatim under `output/.ob/authors/`. Production deployments that need to publish `.ob/` alongside the dataset may strip PII and keep only the SHA-256 author id (originblame paper §6).
- **`source.append` / `source.pop` thread-local stack** — not used; teasecorpus attributes each QA explicitly via `track(source=[hashes])`.

## References

- [OriginBlame paper — arXiv:2607.13037](https://arxiv.org/abs/2607.13037)
- [RFC 6761 — Reserved Top Level DNS Names](https://www.rfc-editor.org/rfc/rfc6761) (`.invalid` TLD)
- [CC-BY-SA-3.0](https://creativecommons.org/licenses/by-sa/3.0/) (wiki license applied to every section)
