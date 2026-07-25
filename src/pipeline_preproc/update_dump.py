#!/usr/bin/env python3
"""update_dump.py — 增量更新 Fandom Wiki XML dump。

基于 ../py-wikieditor/src/dump_xml.py 的 export_incremental_via_special 核心逻辑，
下载自上次全量 dump 以来的增量修订，产出独立 delta XML 文件。

依赖:
  pip install -e ../py-wikieditor

用法:
  python src/pipeline_preprocess/update_dump.py                 # 所有默认命名空间
  python src/pipeline_preprocess/update_dump.py --ns 0          # 只更新 main ns
  python src/pipeline_preprocess/update_dump.py --dry-run       # 预览变更(不下载)

产物:
  wikidump/ns0.delta.<YYYYMMDD-HHMMSS>.xml   # 增量 XML(delta,独立文件)
  wikidump/ns0.deleted.<YYYYMMDD-HHMMSS>.txt  # 删除/移动清单(仅有事件时)
  wikidump/ns0.xml.progress.json              # 更新 last_incremental_* 字段

注意:
  - 基于 list=recentchanges API + revision ID 高水位
  - 默认 30 天窗口; 超过 25 天会 warning
  - 不修改原 ns0.xml 等全量文件
  - 合并增量到全量: 手动执行或重跑 download_dump.py --force
"""

import argparse
from pathlib import Path

from fandom_bot import FandomBot
from src.dump_xml import _resolve_ns_name, export_incremental_via_special

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DUMP_DIR = REPO_ROOT / 'wikidump'


def _ns_filename(ns_id: int, site) -> str:
    custom = {0: 'ns0'}.get(ns_id)
    return custom or _resolve_ns_name(site, ns_id)


def main():
    parser = argparse.ArgumentParser(description='增量更新 Fandom Wiki XML dump')
    parser.add_argument('--ns', type=int, nargs='+',
                        help='命名空间 ID 列表(默认: 0 4)')
    parser.add_argument('--dry-run', action='store_true',
                        help='预览变更但不实际下载')
    parser.add_argument('--delay', type=float, default=1.0,
                        help='请求间延迟秒数(默认 1.0)')
    args = parser.parse_args()

    print('🔗 连接 Wiki ...', flush=True)
    bot = FandomBot()
    site = bot.site
    print(f'✓ 已登录: {site.username}', flush=True)

    ns_targets = args.ns or [0, 4]
    DUMP_DIR.mkdir(parents=True, exist_ok=True)

    if args.dry_run:
        print('\n📋 --dry-run: 列出将检查的命名空间:')
        for ns_id in ns_targets:
            filename = _ns_filename(ns_id, site)
            print(f'  ns={ns_id} → {DUMP_DIR / f"{filename}.xml"}')
        return

    total_delta_revs = 0
    total_deleted = 0

    for ns_id in ns_targets:
        filename = _ns_filename(ns_id, site)
        output_path = DUMP_DIR / f'{filename}.xml'

        if not output_path.exists():
            print(f'\n⚠️  ns={ns_id} ({filename}.xml) 不存在; 请先跑 download_dump.py', flush=True)
            continue

        print(f'\n📁 ns={ns_id} ({filename}) — 增量更新', flush=True)
        result = export_incremental_via_special(
            site, ns_id, str(output_path),
            history=True,
            delay=args.delay,
        )
        total_delta_revs += result['n_new_revisions']
        total_deleted += result['n_deleted']

        delta_name = Path(result['delta_path']).name
        print(f'  ✅ delta: {result["n_changed_pages"]} 页, '
              f'+{result["n_new_revisions"]} revs → {delta_name} '
              f'({result["delta_size"] // 1024}kb)', flush=True)
        if result['deleted_path']:
            del_name = Path(result['deleted_path']).name
            print(f'  📋 deleted: {result["n_deleted"]} 项 → {del_name}', flush=True)

    print(f'\n🎉 共 +{total_delta_revs} 修订 {total_deleted} 删除', flush=True)


if __name__ == '__main__':
    main()
