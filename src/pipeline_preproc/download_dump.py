#!/usr/bin/env python3
"""download_dump.py — Download complete MediaWiki XML dump from Fandom Wiki.

Based on ../py-wikieditor/src/dump_xml.py export_via_special core logic.
Outputs to wikidump/ directory.

Dependencies:
  pip install -e ../py-wikieditor

Usage:
  python src/pipeline_preproc/download_dump.py              # Download all default namespaces
  python src/pipeline_preproc/download_dump.py --ns 0       # Download main ns only
  python src/pipeline_preproc/download_dump.py --force      # Force re-download
  python src/pipeline_preproc/download_dump.py --list-only  # List pages only, no download

Outputs:
  wikidump/ns0.xml                          # Main namespace (0)
  wikidump/Template.xml                     # Template (10)
  wikidump/Category.xml                     # Category (14)
  wikidump/Module.xml                       # Module (828)
  wikidump/<project_name>.xml               # Project (4), e.g. "擅长捉弄的高木同学wiki.xml"
  wikidump/*.progress.json                  # Resumable progress state

Notes:
  - Uses prop=revisions API (special mode), includes complete revision history
  - Each page is fsync'd to disk immediately; re-runs auto-resume from checkpoint
  - Fandom rate limit: default 1s between requests
"""

import argparse
import time
from pathlib import Path

from fandom_bot import FandomBot
from src.dump_xml import _api_url, _resolve_ns_name, export_via_special

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DUMP_DIR = REPO_ROOT / 'wikidump'
DEFAULT_NS = {
    0: 'ns0',       # Pipeline convention: main ns named ns0.xml
    4: None,         # Dynamically resolve project ns wiki name
}


def _map_filename(ns_id: int, site) -> str:
    """Map namespace ID to output filename stem."""
    custom = DEFAULT_NS.get(ns_id)
    if custom is not None:
        return custom
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
