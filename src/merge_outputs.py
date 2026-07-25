"""Merge all per-type data.jsonl files into a single training dataset.

Reads from output/wiki_sft/{chapter,character,episode,music,volume,season,movie}/data.jsonl,
tags each entry with meta.type, and writes output/wiki_sft/all_data.jsonl.
Also prints per-type counts.
"""
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SFT_DIR = REPO_ROOT / 'output' / 'wiki_sft'

TYPES = ['chapter', 'character', 'episode', 'music', 'volume', 'season', 'movie']


def main():
    out_path = SFT_DIR / 'all_data.jsonl'
    total = 0
    counts = {}

    with open(out_path, 'w', encoding='utf-8') as fout:
        for typ in TYPES:
            in_path = SFT_DIR / typ / 'data.jsonl'
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
                        d = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    d.setdefault('meta', {})['type'] = typ
                    fout.write(json.dumps(d, ensure_ascii=False) + '\n')
                    n += 1
            counts[typ] = n
            total += n

    print(f'>> merged: {total} QA -> {out_path}', flush=True)
    print('   per-type:', flush=True)
    for typ in TYPES:
        if counts.get(typ, 0) > 0:
            print(f'     {typ:10s}: {counts[typ]:4d}', flush=True)
    print(f'     {"TOTAL":10s}: {total:4d}', flush=True)


if __name__ == '__main__':
    main()
