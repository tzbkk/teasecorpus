"""OriginBlame integration: register page-level sections + source extractor.

Section = one per source document (wiki page), authors = all contributors of
that page as a group. Follows the paper's three-tier model:
    section_hash = SHA-256({path, authors, license, year})
    path  = page title (unique within the wiki)
    authors = list of all contributor names for that page
"""
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OB_DIR = REPO_ROOT / 'output'
WIKI_LICENSE = 'CC-BY-SA-3.0'
EMAIL_DOMAIN = 'teasecorpus.invalid'  # RFC 6761 — guaranteed NXDOMAIN

DATASET_PATH = 'dataset.jsonl'

# Cherry-pick page title (ns4/project namespace)
TRANSLATION_TABLE_TITLE = '擅长捉弄的高木同学wiki:漫画标题译名表'


def year_range(timestamps: list[str]) -> str:
    """Format year span from revision timestamps.

    Single year  -> "2020"
    Multi year   -> "2018-2026"
    Empty        -> ""
    """
    years = sorted({ts[:4] for ts in timestamps if ts})
    if not years:
        return ""
    return years[0] if len(years) == 1 else f"{years[0]}-{years[-1]}"


def make_email(contributor_id: str) -> str:
    return f'{contributor_id}@{EMAIL_DOMAIN}'


def init_ob() -> None:
    from ob import init
    init(ob_dir=OB_DIR)


def clean_ob() -> int:
    """Merge pending PID files into manifest shards.

    Call at pipeline start (absorb crashed leftovers) and end (queries work
    immediately). No-op when no PID files exist.
    """
    from ob._ob_native import clean as _native_clean
    result = _native_clean(str(OB_DIR), False)
    return result.get('document_merged', 0) if isinstance(result, dict) else 0


# ---------------------------------------------------------------------------
# Section registration (page-level, per paper design)
# ---------------------------------------------------------------------------

def register_page_section(
    page_title: str,
    contributor_names: list[str],
    contributor_ids: dict[str, str],
    year_str: str,
) -> str:
    """Register one section for a single wiki page.

    section = {path=page_title, authors=[all_contributors], license, year}

    Args:
        page_title: wiki page title (unique, serves as `path`).
        contributor_names: all editors of this page (become ob authors).
        contributor_ids: {name -> wiki_id_or_ip} for email generation.
        year_str: union year range of all contributors' timestamps.
    """
    from ob import author_add, register_section
    for name in contributor_names:
        wid = contributor_ids.get(name, name)
        author_add(name=name, email=make_email(wid), ob_dir=OB_DIR)
    return register_section(
        path=page_title,
        authors=contributor_names,
        license=WIKI_LICENSE,
        year=year_str,
        ob_dir=OB_DIR,
    )


def register_all_pages(
    pages_contribs: dict[str, dict[str, list[str]]],
    contributor_ids: dict[str, str],
) -> dict[str, str]:
    """Register one section per wiki page.

    Args:
        pages_contribs: {page_title -> {contributor_name -> [timestamps]}}
        contributor_ids: {contributor_name -> wiki_id_or_ip}

    Returns:
        section_map: {page_title -> section_hash}
    """
    section_map = {}
    for page_title, contribs in sorted(pages_contribs.items()):
        names = sorted(contribs.keys())
        all_ts: list[str] = []
        for ts_list in contribs.values():
            all_ts.extend(ts_list)
        yr = year_range(all_ts)
        section_map[page_title] = register_page_section(
            page_title, names, contributor_ids, yr,
        )
    return section_map


def save_section_map(section_map: dict[str, str]) -> None:
    cache = OB_DIR / '.ob' / 'teasecorpus_section_map.json'
    cache.write_text(
        json.dumps(
            [{'page': title, 'hash': h}
             for title, h in sorted(section_map.items())],
            ensure_ascii=False, indent=2,
        ),
        encoding='utf-8',
    )


def load_section_map() -> dict[str, str]:
    cache = OB_DIR / '.ob' / 'teasecorpus_section_map.json'
    if not cache.exists():
        raise RuntimeError(
            'section_map cache not found; run `python src/setup_ob.py` first')
    data = json.loads(cache.read_text())
    return {d['page']: d['hash'] for d in data}


# ---------------------------------------------------------------------------
# Source extractor (used by pipeline_qa_gen/*.py)
# ---------------------------------------------------------------------------

def make_source_extractor(section_map: dict[str, str]):
    """Return (item, qa_pair=None) -> list[section_hash] | None.

    Looks up the item's wiki page title in section_map. One section per page.
    """
    def extract(item, qa_pair=None):
        title = item.get('title')
        if title and title in section_map:
            return [section_map[title]]
        return None
    return extract


def make_chapter_source_extractor(
    section_map: dict[str, str],
    translation_table: dict,
):
    """Chapter-specific extractor: page section + optional 译名表 section.

    If the chapter has a translation entry, its QA sources include both the
    chapter page section and the translation table page section.
    """
    tt_hash = section_map.get(TRANSLATION_TABLE_TITLE)

    def extract(item, qa_pair=None):
        hashes = []
        title = item.get('title')
        if title and title in section_map:
            hashes.append(section_map[title])
        chap_id = item.get('infobox', {}).get('章节数目', '')
        if chap_id and chap_id in translation_table and tt_hash:
            hashes.append(tt_hash)
        return hashes if hashes else None
    return extract


# ---------------------------------------------------------------------------
# Track helper
# ---------------------------------------------------------------------------

def track_chatml(chatml: dict, file_path: Path, section_hashes: list[str]) -> None:
    """Call ob.track() for a single ChatML record.

    file_path is IGNORED — we always record DATASET_PATH so `ob blame` on the
    final merged file resolves records produced at pipeline time.
    """
    from ob import track
    track(chatml, file=DATASET_PATH, source=section_hashes, ob_dir=OB_DIR)


# ---------------------------------------------------------------------------
# Pipeline helpers (used by all 7 pipeline_qa_gen/*.py scripts)
# ---------------------------------------------------------------------------

def setup_provenance(source_extractor_factory):
    """Initialize provenance tracking for a pipeline run.

    Returns (source_extractor, track_fn) or (None, None) if disabled.
    Cleans leftover PID files from prior crashes.

    Args:
        source_extractor_factory: callable(section_map) -> source_extractor function.
    """
    try:
        section_map = load_section_map()
        clean_ob()
        source_extractor = source_extractor_factory(section_map)
        print('>> ob provenance: ENABLED', flush=True)
        return source_extractor, track_chatml
    except (RuntimeError, ImportError) as e:
        print(f'>> ob provenance: DISABLED ({type(e).__name__}: {e})', flush=True)
        return None, None


def teardown_provenance(track_fn) -> None:
    """Merge PID files after pipeline completion."""
    if track_fn is None:
        return
    try:
        merged = clean_ob()
        print(f'>> ob clean: merged {merged} records', flush=True)
    except Exception as e:
        print(f'>> warning: ob clean failed: {e}', flush=True)
