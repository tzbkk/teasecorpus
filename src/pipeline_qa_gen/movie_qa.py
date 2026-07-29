"""Movie page QA pipeline (1 page, LLM-driven).

Single page (剧场版). Combines infobox (director/writer/studio/release date)
with the full Chinese synopsis extracted from the <tabber> + multi-region
release-date bullets. LLM yields ~8-10 QA covering plot and production.
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # src/

from wiki_parser import load_dump, collect_movies
from llm_client import run_pipeline, anti_tautology_block
from provenance import make_source_extractor, setup_provenance, teardown_provenance


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DUMP_DIR = REPO_ROOT / 'wikidump'

SYSTEM = ('你是一个基于给定资料回答问题的助手。'
          '严格依据提供的字段文本作答,不推测、不编造。'
          '所有问题自包含,不依赖上下文代词。')

TITLE = '剧场版 擅长捉弄的高木同学'


def build_user_prompt(item: dict) -> str:
    f = item['fields']
    parts = [f'基于以下剧场版完整资料产出最多 10 个 QA 对。\n']

    parts.append('【剧场版元数据】')
    parts.append(f'- 标题(必须用作问题中的标识): {TITLE}')
    for key, label in [
        ('日文名', '日文名'), ('罗马音', '罗马音'), ('导演', '导演'),
        ('编剧', '编剧'), ('音乐', '音乐'), ('制作公司', '动画制作公司'),
        ('上映日期', '上映日期'), ('状态', '状态'),
        ('原作', '原作'), ('作者', '作者'),
    ]:
        if f.get(key):
            parts.append(f'- {label}: {f[key]}')
    parts.append('')

    if item['intro']:
        parts.append('【剧场版简介】')
        parts.append(item['intro'])
        parts.append('')

    if item['synopsis']:
        parts.append('【剧场版剧情梗概】')
        parts.append(item['synopsis'])
        parts.append('')

    if item['release_dates']:
        parts.append('【各地区上映时间】')
        for rd in item['release_dates']:
            parts.append(f'- {rd}')
        parts.append('')

    parts.append('【任务流程(内部思考,不输出)】')
    parts.append('1. 候选:基于以上资料,设计 12 个候选问题,每个答案必须能在以上文本里直接找到原文:')
    parts.append('   - 制作类:导演/编剧/音乐/制作公司/作者')
    parts.append('   - 剧情类:剧情梗概中的具体事件(花/猫/暑假/西片与高木的关系演进)')
    parts.append('   - 上映类:各地区上映日期(日本/台湾/中国大陆/香港等)')
    parts.append('   - 元数据类:日文名/罗马音/原作')
    parts.append('2. 配额:10 个 QA 中**至少 5 个必须基于【剧场版剧情梗概】**(剧情是核心价值),')
    parts.append('   制作类不超过 3 个,上映日期类不超过 2 个')
    parts.append('3. 自检:对每个候选问"答案的关键信息能在哪个字段找到?";找不到的直接删除')
    parts.append('4. 多样化:优先保留覆盖不同侧面的;同类型保留 1 个')
    parts.append('5. 输出:最多保留 10 个(若资料稀薄,只输出能通过自检的数量,但至少 5 个)')
    parts.append('')
    parts.append('【硬约束】')
    parts.append('- 答案只能是上述文本的原话或直接转述,不允许跨字段推测、综合、归纳')
    parts.append('- 禁止"体现了..."/"展现了..."/"暗示..."等隐含推断措辞')
    parts.append('- 若发现某候选问题答案不在文本里,**直接删该问题**,不要改成"未提及"')
    parts.append(anti_tautology_block('本剧场版'))
    parts.append('**【Self-contained 硬约束 - 极其重要】**')
    parts.append('每个问题必须自包含,不依赖任何外部上下文即可被独立理解:')
    parts.append('- 禁止使用"本片/这部电影/该剧场版/this movie"等代词指代')
    parts.append(f'- 必须用【标题】作为标识:**{TITLE}**')
    parts.append(f'  示例: "{TITLE}的导演是谁?" 或 "{TITLE}中, 花是谁?"')
    parts.append('- 答案也要避免代词:"他/她/这/那"必须改成具体角色名或对象')
    parts.append('')
    parts.append('【输出格式】(只输出最终保留的 QA,不要输出候选和自检过程)')
    for i in range(1, 11):
        parts.append(f'Q{i}: ...')
        parts.append(f'A{i}: ...')
        parts.append('')
    parts.append('(若不足 10 个,只输出能通过自检的数量,从 Q1 顺延;不要凑数)')
    return '\n'.join(parts)


def template_qa(item: dict) -> list:
    f = item['fields']
    out = []
    if f.get('导演'):
        out.append((f'{TITLE}的导演是谁?', f['导演']))
    if f.get('上映日期'):
        out.append((f'{TITLE}在日本的上映日期是?', f['上映日期']))
    if f.get('制作公司'):
        out.append((f'{TITLE}由哪家公司制作?', f['制作公司']))
    return out


def decontextualize(text: str, item: dict) -> str:
    return re.sub(r'(本片|这部电影|该剧场版|该电影|this movie|the movie)',
                  TITLE, text, flags=re.IGNORECASE)


def main():
    parser = argparse.ArgumentParser(description='Movie QA pipeline (1 page).')
    parser.add_argument('--delay', type=float, default=0.5)
    parser.add_argument('--reset', action='store_true')
    args = parser.parse_args()

    if args.reset:
        cache_dir = REPO_ROOT / 'output' / '.cache'
        for p in [cache_dir / 'movie.jsonl',
                  cache_dir / 'movie.progress.json',
                  cache_dir / 'movie.errors.json']:
            if p.exists():
                p.unlink()
        print('>> --reset: cleared movie output', flush=True)

    print('>> loading dump...', flush=True)
    contents, _, contribs_with_years, _ = load_dump(DUMP_DIR / 'ns0.xml')
    items = collect_movies(contents, contributors_by_page=contribs_with_years)
    print(f'   movies={len(items)}', flush=True)

    source_extractor, track_fn = setup_provenance(make_source_extractor)

    run_pipeline(
        items=items,
        build_prompt=build_user_prompt,
        build_template_qa=template_qa,
        decontextualize=decontextualize,
        system=SYSTEM,
        output_subdir='movie',
        delay=args.delay,
        max_items=0,
        item_id_fn=lambda m: m['title'],
        source_extractor=source_extractor,
        track_fn=track_fn,
    )

    teardown_provenance(track_fn)


if __name__ == '__main__':
    main()
