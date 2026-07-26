"""Volume page QA pipeline (23 pages, template-only).

Template-only by design: 23 volumes share near-identical infobox shape and
chapter-list structure, so LLM-driven QA would produce same-shape questions.
Templates yield ~4-5 distinct QA per volume by combining metadata fields.
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # src/

from wiki_parser import load_dump, collect_volumes
from llm_client import to_chatml, strip_incomplete_jsonl, load_progress, save_progress
from provenance import load_section_map, make_source_extractor, track_chatml, clean_ob


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DUMP_DIR = REPO_ROOT / 'wikidump'
CACHE_DIR = REPO_ROOT / 'output' / '.cache'

SYSTEM = ('你是一个基于给定资料回答问题的助手。'
          '严格依据提供的字段文本作答,不推测、不编造。'
          '所有问题自包含,不依赖上下文代词。')


def template_qa(item: dict) -> list:
    f = item['fields']
    title = item['title']
    out = []

    def add(q, a):
        a_clean = re.sub(r'[《》。.,,!！?？\s]+', '', a)
        title_clean = re.sub(r'[《》。.,,!！?？\s]+', '', title)
        if a_clean and len(a_clean) >= 2 and a_clean in title_clean:
            return
        if a_clean and len(a_clean) >= 2 and a_clean in re.sub(r'[《》。.,,!！?？\s]+', '', q):
            return
        out.append((q, a))

    if f.get('作者'):
        add(f'{title}的作者是谁?', f['作者'])
    if f.get('页数'):
        add(f'{title}共有多少页?', f'{f["页数"]} 页')
    if f.get('发布日期') or f.get('日版发布日期'):
        date = f.get('发布日期') or f['日版发布日期']
        add(f'{title}的发布日期是?', date)
    if f.get('ISBN') or f.get('日版ISBN'):
        isbn = f.get('ISBN') or f['日版ISBN']
        add(f'{title}的 ISBN 是?', isbn)
    if f.get('台版ISBN'):
        add(f'{title}的台版 ISBN 是?', f['台版ISBN'])
    if f.get('台版发布日期'):
        add(f'{title}的台版发布日期是?', f['台版发布日期'])
    if item['chapters']:
        chs = item['chapters']
        if len(chs) >= 2:
            add(f'{title}收录了哪些章节?',
                f'第{chs[0]}到第{chs[-1]}(共 {len(chs)} 章)')
        elif len(chs) == 1:
            add(f'{title}收录了哪些章节?', f'第{chs[0]}')
    return out[:5]


def main():
    parser = argparse.ArgumentParser(description='Volume QA pipeline (23 pages, template-only).')
    parser.add_argument('--max', type=int, default=0)
    parser.add_argument('--reset', action='store_true')
    args = parser.parse_args()

    if args.reset:
        for p in [CACHE_DIR / 'volume.jsonl', CACHE_DIR / 'volume.progress.json']:
            if p.exists():
                p.unlink()
        print('>> --reset: cleared volume output', flush=True)

    print('>> loading dump...', flush=True)
    contents, _, contribs_with_years, _ = load_dump(DUMP_DIR / 'ns0.xml')
    items = collect_volumes(contents, contributors_by_page=contribs_with_years)
    if args.max > 0:
        items = items[:args.max]
    print(f'   volumes={len(items)}', flush=True)

    try:
        section_map = load_section_map()
        source_extractor = make_source_extractor(section_map)
        track_fn = track_chatml
        clean_ob()
        print('>> ob provenance: ENABLED', flush=True)
    except (RuntimeError, ImportError) as e:
        source_extractor = None
        track_fn = None
        print(f'>> ob provenance: DISABLED ({e})', flush=True)

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    data_path = CACHE_DIR / 'volume.jsonl'
    progress_path = CACHE_DIR / 'volume.progress.json'

    valid = strip_incomplete_jsonl(data_path)
    progress = load_progress(progress_path)
    last_idx = progress.get('last_completed_idx', -1)
    done_qa = progress.get('done_qa', valid)

    total = len(items)
    print(f'>> pipeline: {total} items, resuming from idx {last_idx + 1}, '
          f'{done_qa} QA in volume.jsonl', flush=True)

    with open(data_path, 'a', encoding='utf-8') as fout:
        for idx in range(last_idx + 1, total):
            item = items[idx]
            qa_pairs = template_qa(item)
            source_hashes = (source_extractor(item) if source_extractor else None)
            for q, a in qa_pairs:
                chatml = to_chatml(SYSTEM, q, a)
                fout.write(json.dumps(chatml, ensure_ascii=False) + '\n')
                if track_fn is not None and source_hashes:
                    try:
                        track_chatml(chatml, data_path, source_hashes)
                    except Exception as e:
                        print(f'  track failed: {e}', flush=True)
            fout.flush()
            done_qa += len(qa_pairs)
            save_progress(progress_path, {
                'last_completed_idx': idx, 'done_qa': done_qa,
                'last_id': item['title'], 'timestamp': time.time(),
            })
            print(f'  [{idx + 1}/{total}] {item["title"]} +{len(qa_pairs)} '
                  f'(total {done_qa})', flush=True)

    print(f'\n>> done: {done_qa} QA in {data_path}', flush=True)

    if track_fn is not None:
        try:
            merged = clean_ob()
            print(f'>> ob clean: merged {merged} records', flush=True)
        except Exception as e:
            print(f'>> warning: ob clean failed: {e}', flush=True)


if __name__ == '__main__':
    main()
