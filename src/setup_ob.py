import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from wiki_parser import load_dump, load_cherry_pick_page
from provenance import (
    init_ob, register_all_pages, save_section_map,
    TRANSLATION_TABLE_TITLE, OB_DIR,
)


def main():
    ns0_path = OB_DIR.parent / 'wikidump' / 'ns0.xml'
    wiki_path = OB_DIR.parent / 'wikidump' / '擅长捉弄的高木同学wiki.xml'

    print('>> parsing ns0.xml (per-page contributors)...', flush=True)
    _, _, contribs_with_years, contrib_ids = load_dump(ns0_path)
    page_count = len(contribs_with_years)
    contributor_set = set(contrib_ids.keys())
    print(f'   ns0.xml: {page_count} pages, {len(contributor_set)} unique contributors')

    print('>> cherry-pick 译名表...', flush=True)
    _, cherry_contribs, cherry_ids = load_cherry_pick_page(
        wiki_path,
        page_title=TRANSLATION_TABLE_TITLE,
    )
    contribs_with_years[TRANSLATION_TABLE_TITLE] = cherry_contribs
    contrib_ids.update(cherry_ids)
    print(f'   译名表: {len(cherry_contribs)} contributors')

    print('>> init .ob/ ...', flush=True)
    init_ob()

    print(f'>> registering {len(contribs_with_years)} page-level sections...', flush=True)
    section_map = register_all_pages(contribs_with_years, contrib_ids)
    print(f'   registered {len(section_map)} sections')

    save_section_map(section_map)
    print(f'   cache saved at {OB_DIR / ".ob" / "teasecorpus_section_map.json"}')


if __name__ == '__main__':
    main()
