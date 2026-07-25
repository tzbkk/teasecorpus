#!/usr/bin/env python3
"""download_dump.py — 从 Fandom Wiki 下载完整 MediaWiki XML dump。

基于 ../py-wikieditor/src/dump_xml.py 的 export_via_special 核心逻辑，
输出到本项目的 wikidump/ 目录，使用与下游 pipeline 一致的命名约定。

依赖:
  pip install -e ../py-wikieditor

用法:
  python src/pipeline_preprocess/download_dump.py              # 下载所有默认命名空间
  python src/pipeline_preprocess/download_dump.py --ns 0       # 只下载 main ns
  python src/pipeline_preprocess/download_dump.py --force      # 强制重新下载
  python src/pipeline_preprocess/download_dump.py --list-only  # 只列出页面，不下载

产物:
  wikidump/ns0.xml                          # main namespace (0)
  wikidump/Template.xml                     # Template (10)
  wikidump/Category.xml                     # Category (14)
  wikidump/Module.xml                       # Module (828)
  wikidump/<project_name>.xml               # Project (4), 如 "擅长捉弄的高木同学wiki.xml"
  wikidump/*.progress.json                  # 断点续传状态

注意:
  - 走 prop=revisions API (special mode), 包含完整 revision history
  - 每页拉完立即 fsync 到磁盘, 重跑自动从断点续
  - Fandom 速率限制: 请求间隔默认 1s
"""

import argparse
import time
from pathlib import Path

from fandom_bot import FandomBot
from src.dump_xml import _api_url, _resolve_ns_name, export_via_special

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DUMP_DIR = REPO_ROOT / 'wikidump'
DEFAULT_NS = {
    0: 'ns0',       # 我们 pipeline 约定 main ns 命名为 ns0.xml
    4: None,         # 动态解析 project ns 的 wiki 名称
}


def _map_filename(ns_id: int, site) -> str:
    """将命名空间 ID 映射为输出文件名(不含扩展名)。"""
    custom = DEFAULT_NS.get(ns_id)
    if custom is not None:
        return custom
    # 默认回退到 MediaWiki 命名空间名称
    return _resolve_ns_name(site, ns_id)


def main():
    parser = argparse.ArgumentParser(description='下载 Fandom Wiki 完整 XML dump')
    parser.add_argument('--ns', type=int, nargs='+',
                        help='命名空间 ID 列表(默认: 0 4)')
    parser.add_argument('--list-only', action='store_true',
                        help='只列出页面标题，不下载')
    parser.add_argument('--force', action='store_true',
                        help='忽略进度和已有文件，强制重新下载')
    parser.add_argument('--delay', type=float, default=1.0,
                        help='请求间延迟秒数(默认 1.0)')
    args = parser.parse_args()

    # 连接 Wiki
    print('🔗 连接 Wiki ...', flush=True)
    bot = FandomBot()
    site = bot.site
    print(f'✓ 已登录: {site.username}', flush=True)

    # 解析目标命名空间
    if args.ns:
        ns_targets = args.ns
    else:
        ns_targets = list(DEFAULT_NS.keys())

    DUMP_DIR.mkdir(parents=True, exist_ok=True)

    total_pages = 0
    total_size = 0

    for ns_id in ns_targets:
        filename = _map_filename(ns_id, site)
        output_path = DUMP_DIR / f'{filename}.xml'
        print(f'\n📁 命名空间 {ns_id} → {output_path}', flush=True)

        if args.force and output_path.exists():
            output_path.unlink()
            progress = output_path.with_suffix('.xml.progress.json')
            if progress.exists():
                progress.unlink()

        if args.list_only:
            url = _api_url(site)
            titles = []
            apfrom = None
            while True:
                params = {
                    'action': 'query', 'list': 'allpages',
                    'apnamespace': str(ns_id), 'aplimit': '500', 'format': 'json',
                }
                if apfrom:
                    params['apfrom'] = apfrom
                import requests
                r = requests.get(url, params=params, timeout=300)
                r.raise_for_status()
                data = r.json()
                titles.extend(p['title'] for p in data.get('query', {}).get('allpages', []))
                cont = data.get('continue') or {}
                apfrom = cont.get('apcontinue') or cont.get('apfrom')
                if not apfrom:
                    break
                time.sleep(args.delay)
            for t in titles:
                print(f'  • {t}')
            print(f'  ✅ {filename}/ 共 {len(titles)} 页', flush=True)
            total_pages += len(titles)
            continue

        # 实际下载
        n_pages, size_bytes = export_via_special(
            site, ns_id, str(output_path),
            history=True,
            delay=args.delay,
        )
        total_pages += n_pages
        total_size += size_bytes
        print(f'  ✅ {filename}: {n_pages} 页, {size_bytes // 1024}kb', flush=True)

    if not args.list_only:
        print(f'\n🎉 共 {total_pages} 页, {total_size // 1024}kb', flush=True)


if __name__ == '__main__':
    main()
