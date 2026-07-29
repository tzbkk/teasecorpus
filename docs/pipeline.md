# Pipeline

## Overview

```
download_dump.py          Fandom API → wikidump/*.xml
        ↓
wiki_parser.py            XML → structured items (with contributors + timestamps)
        ↓
setup_ob.py (one-time)    contributors → .ob/authors/ + .ob/sections/
        ↓
pipeline_qa_gen/*.py      LLM / template → output/.cache/{type}.jsonl
        ↓                          ↓
                        ob.track(file='dataset.jsonl') → .ob/document-index/
        ↓
merge_outputs.py          output/.cache/*.jsonl → dataset.jsonl (byte-level concatenation)
```

## Preprocessing (preproc)

**`download_dump.py`**: Downloads complete XML dump from Fandom wiki.

- Uses `prop=revisions` API, includes complete revision history
- Default namespaces: 0 (main) + 4 (project)
- Output: `wikidump/ns0.xml` + `wikidump/<project_name>.xml`
- Resumable: `.progress.json` records progress, can resume after interruption

**`update_dump.py`**: Incrementally updates existing dump.

- Based on `list=recentchanges` API + revision ID high watermark
- Produces independent delta XML + deletion list
- Does not modify original full dump file

## Parser

**`wiki_parser.py`**: Shared MediaWiki XML parser.

Core functions:

```python
# Load dump
contents, redirect_map, contribs_with_years, contributor_ids = load_dump('wikidump/ns0.xml')

# Extract single page from specified dump (for cherry-picking translation tables)
text, contribs_with_years, contrib_ids = load_cherry_pick_page(
    'wikidump/擅长捉弄的高木同学wiki.xml',
    page_title='擅长捉弄的高木同学wiki:漫画标题译名表',
)

# Collect by category (can accept contributors_by_page=None kwarg)
chapters = collect_chapters(contents, contributors_by_page=contribs_with_years)       # Chapter N
volumes = collect_volumes(contents, contributors_by_page=contribs_with_years)         # Volume N
characters = collect_characters(contents, contributors_by_page=contribs_with_years)   # Character pages
episodes = collect_episodes(contents, contributors_by_page=contribs_with_years)       # Episode pages
music_items = collect_music(contents, contributors_by_page=contribs_with_years)       # Music pages
seasons = collect_seasons(contents, contributors_by_page=contribs_with_years)         # Season pages
```

**`load_dump` returns 4-tuple**:
- `contents`: `list[(title, text)]` — Title and text of non-redirect pages
- `redirect_map`: `dict[src_title: target_title]` — Redirect mapping
- `contribs_with_years`: `dict[title, dict[contributor_name, list[timestamp]]]` — All revision timestamps for each page's each contributor
- `contributor_ids`: `dict[contributor_name, wiki_id_or_ip]` — Contributor name to stable ID mapping

**`collect_*` functions** now accept optional `contributors_by_page=None` kwarg, when provided will attach `'contributors': set[name]` field to each item.

Returned item dict structure (using chapter as example):

```python
{
    'title': '漫画第10章',
    'infobox': {'章节数目': '10', '名称': '橡皮擦', '发布日期': '...', ...},
    'summary': '...',
    'characters': ['高木同学', '西片', ...],
    'location': '...',
    'trivia': '...',
    'quote': ('台词', '说话者'),  # or None
    'contributors': {'铁桶', 'Lunisha Kumina', ...},  # Only when contributors_by_page is passed
}
```

## QA Generation

### LLM pipeline (chapters/characters/episodes/seasons/movies)

```
item → build_prompt() → call_llm() → parse_response() → filter_tautological() → QA pairs
                                                                    ↑
                              template_qa fallback                        ↓
                             (on LLM fail/empty/wrong format)     to_chatml()
```

`run_pipeline()` unified control:
- Resumable: flush + fsync after each item completion, ensures data safety
- Error recovery: single page failure doesn't affect other pages
- Empty QA fallback: when LLM fails/empty output, use `build_template_qa()`
- Provenance tracking (optional): integrate via originblame through `source_extractor` + `track_fn` parameters

```python
run_pipeline(
    items, build_prompt, build_template_qa, decontextualize,
    system, output_subdir, delay, max_items, item_id_fn,
    source_extractor=None,  # optional: (item, qa_pair) -> list[section_hash] | None
    track_fn=None,          # optional: (chatml, file_path, section_hashes) -> None
)
```

Branch cleanup:

```python
# Decontextualize on concatenation (remove "this chapter/this episode/this character")
qa_pairs = decontextualize(qa_pairs, item_title)

# Filter tautological (answer = title or chapter number)
qa_pairs = filter_tautological(qa_pairs, item_title)
```

### Template pipeline (music/volumes)

Template-only, no LLM:

```python
if has_summary:
    template_qa_for_volume(item)    # Volume QA
    template_qa_for_music(item)      # Music QA
```

Both have independent `main()` functions, don't use `run_pipeline()`.

## Merge

**`merge_outputs.py`**: Scans `{type}.jsonl` under `output/.cache/`, byte-level concatenates to `dataset.jsonl` at repo root. Doesn't modify content, so line_hash remains stable from pipeline → dataset.jsonl.

## Edge Case Testing

**`edge_tests.py`**: 22 hard samples (including special templates, sections, nested structures, etc.), covering edge cases for all page types. Most pipeline scripts can validate in small batches via `--max` parameter (`chapter_qa.py` uses `--max-chapters`, `movie_qa.py` doesn't have this parameter).

## Provenance (ob integration)

Pipeline supports record-level provenance tracking, integrate via originblame through `source_extractor` + `track_fn` parameters.

**Integration modes**:
- `chapter_qa.py` — Custom source_extractor, translation-type QA includes 铁桶 (translation table section)
- `character/episode/season/movie_qa.py` — Standard source_extractor via `make_source_extractor`
- `music/volume_qa.py` — Template-only, manually calls `track_chatml` in inner loop

**line_hash stability**: merge byte-level concatenation doesn't modify content, line_hash remains consistent from pipeline → dataset.jsonl.

**Data flow**:
```
setup_ob.py (one-time) → Register 24 sections (23 contributors + 铁桶@translation table)
                        ↓
During pipeline run → track(file='dataset.jsonl') writes .ob/docidx.{pid} → clean_ob() merge
                        ↓
Query capability   → ob blame -d output/ output/dataset.jsonl N / ob show / ob revoke / ob purge
```

See [Provenance Deep Dive](provenance.md) for details.