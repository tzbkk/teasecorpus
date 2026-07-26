"""Anime season page QA pipeline (3 pages, LLM-driven).

Only 3 pages (seasons 1/2/3), each densely populated with staff / studio /
airdate / episode count / synopsis. LLM extracts ~5-8 QA per season.
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # src/

from wiki_parser import load_dump, collect_seasons
from llm_client import run_pipeline, anti_tautology_block
from provenance import load_section_map, make_source_extractor, track_chatml, clean_ob


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DUMP_DIR = REPO_ROOT / 'wikidump'

SYSTEM = ('你是一个基于给定资料回答问题的助手。'
          '严格依据提供的字段文本作答,不推测、不编造。'
          '所有问题自包含,不依赖上下文代词。')


def build_user_prompt(item: dict) -> str:
    f = item['fields']
    title = item['title']
    parts = [f'基于以下动画季度完整资料产出最多 6 个 QA 对。\n']

    parts.append('【季度元数据】')
    parts.append(f'- 完整季度标题(必须用作问题中的标识): {title}')
    for key, label in [
        ('名称', '名称'), ('导演', '导演'), ('编剧', '编剧'),
        ('音乐', '音乐制作'), ('制作公司', '动画制作公司'),
        ('集数', '集数'), ('播放时间', '播放时间'),
        ('播放状态', '播放状态'), ('原作', '原作'),
        ('作者', '作者'), ('上一季', '上一季'), ('下一季', '下一季'),
    ]:
        if f.get(key):
            parts.append(f'- {label}: {f[key]}')
    parts.append('')

    if item['synopsis']:
        parts.append('【内容简介】')
        parts.append(item['synopsis'])
        parts.append('')

    parts.append('【任务流程(内部思考,不输出)】')
    parts.append('1. 候选:基于以上资料,设计 7-8 个候选问题,每个问题的答案**必须能在以上文本里直接找到原文**:')
    parts.append('   - 制作信息类:问导演/编剧/音乐/制作公司/集数')
    parts.append('   - 播出信息类:问播放时间/状态/上一季/下一季')
    parts.append('   - 原作类:问原作/作者')
    parts.append('   - 内容类:基于内容简介问剧情概述(仅当 synopsis 非空)')
    parts.append('2. 配额:6 个 QA 中**至少 2 个必须基于【内容简介】**(若 synopsis 非空),')
    parts.append('   元数据类不超过 4 个')
    parts.append('3. 自检:对每个候选问"答案的关键信息能在哪个字段找到?";找不到的直接删除')
    parts.append('4. 多样化:优先保留覆盖不同侧面的;同类型(如多个制作人员类)保留 1 个')
    parts.append('5. 输出:最多保留 6 个(若资料稀薄,只输出 1-2 个也可接受,但至少 1 个)')
    parts.append('')
    parts.append('【硬约束】')
    parts.append('- 答案只能是上述文本的原话或直接转述,不允许跨字段推测、综合、归纳')
    parts.append('- 禁止"体现了..."/"展现了..."/"暗示..."等隐含推断措辞')
    parts.append('- 若发现某候选问题答案不在文本里,**直接删该问题**,不要改成"未提及"')
    parts.append(anti_tautology_block('本季度'))
    parts.append('**【Self-contained 硬约束 - 极其重要】**')
    parts.append('每个问题必须自包含,不依赖任何外部上下文即可被独立理解:')
    parts.append('- 禁止使用"本季度/这一季/该季/this season"等代词指代')
    parts.append(f'- 必须用【完整季度标题】作为标识:**{title}**')
    parts.append(f'  示例(本季度): "{title}的导演是谁?"')
    parts.append('- 答案也要避免代词:"他/她/这/那"必须改成具体角色名或对象')
    parts.append('')
    parts.append('【输出格式】(只输出最终保留的 QA,不要输出候选和自检过程)')
    for i in range(1, 7):
        parts.append(f'Q{i}: ...')
        parts.append(f'A{i}: ...')
        parts.append('')
    parts.append('(若不足 6 个,只输出能通过自检的数量,从 Q1 顺延;不要凑数)')
    return '\n'.join(parts)


def template_qa(item: dict) -> list:
    f = item['fields']
    title = item['title']
    out = []
    if f.get('导演'):
        out.append((f'{title}的导演是谁?', f['导演']))
    if f.get('制作公司'):
        out.append((f'{title}由哪家公司制作?', f['制作公司']))
    if f.get('播放时间'):
        out.append((f'{title}的播放时间是什么?', f['播放时间']))
    return out


def decontextualize(text: str, item: dict) -> str:
    title = item['title']
    return re.sub(r'(本季度|这一季|该季|此季|this season)',
                  title, text, flags=re.IGNORECASE)


def main():
    parser = argparse.ArgumentParser(description='Season QA pipeline (3 pages).')
    parser.add_argument('--max', type=int, default=0)
    parser.add_argument('--delay', type=float, default=0.5)
    parser.add_argument('--reset', action='store_true')
    args = parser.parse_args()

    if args.reset:
        cache_dir = REPO_ROOT / 'output' / '.cache'
        for p in [cache_dir / 'season.jsonl',
                  cache_dir / 'season.progress.json',
                  cache_dir / 'season.errors.json']:
            if p.exists():
                p.unlink()
        print('>> --reset: cleared season output', flush=True)

    print('>> loading dump...', flush=True)
    contents, _, contribs_with_years, _ = load_dump(DUMP_DIR / 'ns0.xml')
    items = collect_seasons(contents, contributors_by_page=contribs_with_years)
    print(f'   seasons={len(items)}', flush=True)

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

    run_pipeline(
        items=items,
        build_prompt=build_user_prompt,
        build_template_qa=template_qa,
        decontextualize=decontextualize,
        system=SYSTEM,
        output_subdir='season',
        delay=args.delay,
        max_items=args.max,
        item_id_fn=lambda s: s['title'],
        source_extractor=source_extractor,
        track_fn=track_fn,
    )

    if track_fn is not None:
        try:
            merged = clean_ob()
            print(f'>> ob clean: merged {merged} records', flush=True)
        except Exception as e:
            print(f'>> warning: ob clean failed: {e}', flush=True)


if __name__ == '__main__':
    main()
