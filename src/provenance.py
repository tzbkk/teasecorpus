"""OriginBlame integration: register authors/sections + provide source extractor."""
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OB_DIR = REPO_ROOT / 'output'
WIKI_LICENSE = 'CC-BY-SA-3.0'
EMAIL_DOMAIN = 'teasecorpus.invalid'  # RFC 6761 — guaranteed NXDOMAIN,不可送达

# Canonical published dataset path, relative to OB_DIR. Always recorded as
# the `file` metadata on ob.track(), even when the file does not exist yet
# at pipeline time: `ob blame -d output/ dataset.jsonl N` looks up by line
# hash, ignoring the recorded file path.
DATASET_PATH = 'dataset.jsonl'

# Section sources
NS0_PATH = 'wikidump/ns0.xml'
TRANSLATION_TABLE_PATH = 'wikidump/擅长捉弄的高木同学wiki.xml::漫画标题译名表'
CHERRY_PICK_AUTHOR = '铁桶'  # 译名表唯一 contributor


def year_range(timestamps: list[str]) -> str:
    """Format contributor's year span from revision timestamps.

    Single year  -> "2020"
    Multi year   -> "2018-2026"
    Empty        -> ""
    """
    years = sorted({ts[:4] for ts in timestamps if ts})
    if not years:
        return ""
    return years[0] if len(years) == 1 else f"{years[0]}-{years[-1]}"


def make_email(contributor_id: str) -> str:
    """Generate stable per-user email from wiki contributor ID.

    Format: {wiki_id}@teasecorpus.invalid
    Used as ob revoke --email lookup key (per-user unique).
    For IP contributors without <id>, contrib_id = IP itself.
    """
    return f'{contributor_id}@{EMAIL_DOMAIN}'


def init_ob() -> None:
    """Idempotent: create .ob/ in repo root."""
    from ob import init
    init(ob_dir=OB_DIR)


def clean_ob() -> int:
    """Merge any pending PID files into the manifest shards.

    Call at pipeline start (to absorb leftover PID files from crashed
    previous runs) and at pipeline end (so `ob blame` works immediately).
    Safe to call when no PID files exist (no-op). Returns merged record count.
    """
    from _ob_native import clean as _native_clean
    result = _native_clean(str(OB_DIR), False)
    return result.get('document_merged', 0) if isinstance(result, dict) else 0


def register_section_for(source_path: str, contributor: str,
                          contrib_id: str, year_str: str) -> str:
    """Register one (source_path, contributor, contrib_id, year_range) -> section_hash.

    contributor: wiki username or IP string (used as ob author 'name').
    contrib_id: wiki <id> (Fandom global), or IP for anonymous contributors.
    year_str: contributor's year range at this source, e.g. "2018-2026".
    """
    from ob import author_add, register_section
    author_add(name=contributor, email=make_email(contrib_id), ob_dir=OB_DIR)
    return register_section(
        path=source_path,
        authors=[contributor],   # 传 name,内部 _resolve_author_ids 会 name lookup
        license=WIKI_LICENSE,
        year=year_str,
        ob_dir=OB_DIR,
    )


def register_all_sections(
    ns0_info: dict[str, tuple[str, str]],
    cherry_pick_info: dict[str, tuple[str, str]] | None = None,
) -> dict[tuple[str, str], str]:
    """Register all sections. Returns section_map cache.

    Args:
        ns0_info: {contributor -> (wiki_id, year_range_str)}
            e.g. {'铁桶': ('32416701', '2018-2026'), ...}
        cherry_pick_info: same format, for cherry-pick page contributors

    Returns:
        Keys: (source_path, contributor) -> section_hash
    """
    section_map = {}
    for c, (wid, yr) in sorted(ns0_info.items()):
        section_map[(NS0_PATH, c)] = register_section_for(NS0_PATH, c, wid, yr)
    if cherry_pick_info:
        for c, (wid, yr) in sorted(cherry_pick_info.items()):
            section_map[(TRANSLATION_TABLE_PATH, c)] = register_section_for(
                TRANSLATION_TABLE_PATH, c, wid, yr)
    return section_map


def save_section_map(section_map: dict[tuple[str, str], str]) -> None:
    """Persist section_map as JSON (tuple key -> list)."""
    cache = OB_DIR / '.ob' / 'teasecorpus_section_map.json'
    cache.write_text(
        json.dumps(
            [{'source': s, 'contributor': c, 'hash': h}
             for (s, c), h in section_map.items()],
            ensure_ascii=False, indent=2,
        ),
        encoding='utf-8',
    )


def load_section_map() -> dict[tuple[str, str], str]:
    """Load section_map cache (inverse of save)."""
    cache = OB_DIR / '.ob' / 'teasecorpus_section_map.json'
    if not cache.exists():
        raise RuntimeError(
            'section_map cache not found; run `python3 src/setup_ob.py` first')
    data = json.loads(cache.read_text())
    return {(d['source'], d['contributor']): d['hash'] for d in data}


def make_source_extractor(
    section_map: dict[tuple[str, str], str],
    source_path: str = 'wikidump/ns0.xml',
    extra_source_paths: list[str] | None = None,
):
    """Return a function (item, qa_pair=None) -> list[section_hash] | None.

    - 普通 QA:返回 item.contributors 对应的 section hashes
    - 若 extra_source_paths 提供,且 item 标记为 'uses_extra'(如译名表 QA),
      会附加 extra_source_paths 的所有 contributors 的 section hashes
    """
    extra_source_paths = extra_source_paths or []

    def extract(item, qa_pair=None):
        contributors = item.get('contributors', set())
        hashes = [
            section_map[(source_path, c)]
            for c in contributors
            if (source_path, c) in section_map
        ]
        if item.get('uses_extra'):
            for sp in extra_source_paths:
                for (s, c), h in section_map.items():
                    if s == sp:
                        hashes.append(h)
        return hashes if hashes else None

    return extract


def track_chatml(chatml: dict, file_path: Path, section_hashes: list[str]) -> None:
    """Call ob.track() for a single ChatML record.

    The `file_path` argument is intentionally IGNORED: we always record
    DATASET_PATH (the canonical published dataset) so that `ob blame` on the
    final merged file resolves records produced at pipeline time, even though
    dataset.jsonl does not exist until merge_outputs.py runs. This works
    because the Rust `ob blame FILE N` implementation ignores FILE and looks
    up by line content hash. The parameter is kept for signature backward
    compatibility with pipeline callers.
    """
    from ob import track
    track(chatml, file=DATASET_PATH, source=section_hashes, ob_dir=OB_DIR)
