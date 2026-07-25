"""One-time setup: parse ns0.xml + cherry-pick page, register to .ob/."""
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from wiki_parser import NS, load_dump, load_cherry_pick_page
from provenance import (
    init_ob, register_all_sections, save_section_map, year_range,
    OB_DIR, NS0_PATH, TRANSLATION_TABLE_PATH, CHERRY_PICK_AUTHOR,
)


def main():
    print('>> parsing ns0.xml contributors + timestamps + IDs...', flush=True)
    _, _, contribs_with_years, contrib_ids = load_dump(OB_DIR.parent / 'wikidump' / 'ns0.xml')
    # 聚合到 (dump-level) per-contributor timestamps list
    ns0_ts = defaultdict(list)
    for page_contribs in contribs_with_years.values():
        for c, timestamps in page_contribs.items():
            ns0_ts[c].extend(timestamps)
    # 构建 per-contributor info: (wiki_id, year_range)
    ns0_info = {
        c: (contrib_ids.get(c, c), year_range(ts))
        for c, ts in ns0_ts.items()
    }
    print(f'   ns0.xml: {len(ns0_info)} unique contributors')
    for c in ['铁桶', 'Lunisha Kumina', 'BJTZ', 'FANDOM']:
        if c in ns0_info:
            wid, yr = ns0_info[c]
            print(f'     {c}: id={wid} email={wid}@teasecorpus.invalid year={yr!r}')

    print('>> parsing cherry-pick page contributors + timestamps + IDs...', flush=True)
    _, cherry_contribs_with_years, cherry_contrib_ids = load_cherry_pick_page(
        OB_DIR.parent / 'wikidump' / '擅长捉弄的高木同学wiki.xml',
        page_title='擅长捉弄的高木同学wiki:漫画标题译名表',
    )
    cherry_info = {
        c: (cherry_contrib_ids.get(c, c), year_range(ts))
        for c, ts in cherry_contribs_with_years.items()
    }
    for c, (wid, yr) in cherry_info.items():
        print(f'   译名表: {c} id={wid} email={wid}@teasecorpus.invalid year={yr!r}')

    print('>> init .ob/ ...', flush=True)
    init_ob()

    print('>> registering authors + sections...', flush=True)
    section_map = register_all_sections(ns0_info, cherry_info)
    print(f'   registered {len(section_map)} sections')
    print(f'     - ns0.xml: {sum(1 for (s, _) in section_map if s == NS0_PATH)}')
    print(f'     - 译名表: {sum(1 for (s, _) in section_map if s == TRANSLATION_TABLE_PATH)}')

    save_section_map(section_map)
    print(f'   cache saved at {OB_DIR / ".ob" / "teasecorpus_section_map.json"}')


if __name__ == '__main__':
    main()
