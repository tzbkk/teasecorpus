"""Music page QA pipeline (41 pages, template-only).

Template-only by design: 41 songs share near-identical infobox shape, so
LLM-driven QA would produce same-shape "X 的演唱者?" × 41.
Templates yield ~2-3 distinct QA per song via fixed field combinations.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # src/

from wiki_parser import load_dump, collect_music
from llm_client import to_chatml, strip_incomplete_jsonl, load_progress, save_progress, load_env


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DUMP_DIR = REPO_ROOT / 'wikidump'
OUTPUT_DIR = REPO_ROOT / 'output' / 'wiki_sft' / 'music'

SYSTEM = ('你是《擅长捉弄的高木同学》wiki 知识助手。'
          '根据用户问题,基于音乐元数据给出准确答案。')


def template_qa(item: dict) -> list:
    f = item['fields']
    title = item['title']
    out = []
    if f.get('演唱'):
        out.append((f'《{title}》的演唱者是谁?', f['演唱']))
    if f.get('作曲'):
        out.append((f'《{title}》的作曲是谁?', f['作曲']))
    if f.get('作词'):
        out.append((f'《{title}》的作词是谁?', f['作词']))
    if f.get('使用范围'):
        out.append((f'《{title}》用作哪一集的音乐?', f['使用范围']))
    if f.get('编曲'):
        out.append((f'《{title}》的编曲是谁?', f['编曲']))
    return out[:3]


def main():
    parser = argparse.ArgumentParser(description='Music QA pipeline (41 pages, template-only).')
    parser.add_argument('--max', type=int, default=0)
    parser.add_argument('--reset', action='store_true')
    args = parser.parse_args()

    if args.reset:
        for p in [OUTPUT_DIR / 'data.jsonl', OUTPUT_DIR / '.progress.json']:
            if p.exists():
                p.unlink()
        print('>> --reset: cleared music output', flush=True)

    print('>> loading dump...', flush=True)
    contents, _ = load_dump(DUMP_DIR / 'ns0.xml')
    items = collect_music(contents)
    if args.max > 0:
        items = items[:args.max]
    print(f'   music={len(items)}', flush=True)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    data_path = OUTPUT_DIR / 'data.jsonl'
    progress_path = OUTPUT_DIR / '.progress.json'

    valid = strip_incomplete_jsonl(data_path)
    progress = load_progress(progress_path)
    last_idx = progress.get('last_completed_idx', -1)
    done_qa = progress.get('done_qa', valid)

    total = len(items)
    print(f'>> pipeline: {total} items, resuming from idx {last_idx + 1}, '
          f'{done_qa} QA in data.jsonl', flush=True)

    with open(data_path, 'a', encoding='utf-8') as fout:
        for idx in range(last_idx + 1, total):
            item = items[idx]
            qa_pairs = template_qa(item)
            for q, a in qa_pairs:
                meta = {'id': item['title'], 'source': 'wikidump/ns0.xml',
                        'license': 'CC-BY-SA-3.0'}
                chatml = to_chatml(SYSTEM, q, a, meta)
                fout.write(json.dumps(chatml, ensure_ascii=False) + '\n')
            fout.flush()
            done_qa += len(qa_pairs)
            save_progress(progress_path, {
                'last_completed_idx': idx, 'done_qa': done_qa,
                'last_id': item['title'], 'timestamp': __import__('time').time(),
            })
            print(f'  [{idx + 1}/{total}] {item["title"]} +{len(qa_pairs)} '
                  f'(total {done_qa})', flush=True)

    print(f'\n>> done: {done_qa} QA in {data_path}', flush=True)


if __name__ == '__main__':
    main()
