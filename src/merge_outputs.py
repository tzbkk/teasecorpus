"""Merge per-type cache files into the canonical dataset.jsonl.

Reads output/.cache/{type}.jsonl, concatenates byte-for-byte (meta.type
already set at pipeline time, so line_hash is stable from pipeline ->
final), writes to repository-root dataset.jsonl (sibling of .ob/).
"""
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = REPO_ROOT / 'output' / '.cache'
DATASET_PATH = REPO_ROOT / 'output' / 'dataset.jsonl'

TYPES = ['chapter', 'character', 'episode', 'music', 'volume', 'season', 'movie']


def main():
    total = 0
    counts = {}
    with open(DATASET_PATH, 'w', encoding='utf-8') as fout:
        for typ in TYPES:
            in_path = CACHE_DIR / f'{typ}.jsonl'
            if not in_path.exists():
                counts[typ] = 0
                continue
            n = 0
            with open(in_path, 'r', encoding='utf-8') as fin:
                for line in fin:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        json.loads(line)  # validate only, don't modify
                    except json.JSONDecodeError:
                        continue
                    fout.write(line + '\n')
                    n += 1
            counts[typ] = n
            total += n

    print(f'>> merged: {total} QA -> {DATASET_PATH}', flush=True)
    print('   per-type:', flush=True)
    for typ in TYPES:
        if counts.get(typ, 0) > 0:
            print(f'     {typ:10s}: {counts[typ]:4d}', flush=True)
    print(f'     {"TOTAL":10s}: {total:4d}', flush=True)


if __name__ == '__main__':
    main()
