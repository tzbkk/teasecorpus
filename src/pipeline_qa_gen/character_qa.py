"""Character page QA pipeline (14 pages, LLM-driven).

Each character page yields ~4-5 QA pairs covering personality / relations /
trivia (high differentiation value) plus at most 2 metadata QA (voice actor,
class, etc.) to avoid cross-character same-shape questions.
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # src/

from wiki_parser import load_dump, collect_characters
from llm_client import run_pipeline, anti_tautology_block
from provenance import load_section_map, make_source_extractor, track_chatml, clean_ob


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DUMP_DIR = REPO_ROOT / 'wikidump'

SYSTEM = ('你是一个基于给定资料回答问题的助手。'
          '严格依据提供的字段文本作答,不推测、不编造。'
          '所有问题自包含,不依赖上下文代词。')


def build_user_prompt(item: dict) -> str:
    f = item['fields']
    name = f.get('名称', item['title'])
    parts = [f'基于以下角色完整资料产出最多 5 个 QA 对。\n']

    parts.append('【角色元数据】')
    parts.append(f'- 角色名(必须用作问题中的角色标识): {name}')
    if f.get('别称'):
        parts.append(f'- 别称: {f["别称"]}')
    if f.get('日文名'):
        parts.append(f'- 日文名: {f["日文名"]}')
    if f.get('罗马音'):
        parts.append(f'- 罗马音: {f["罗马音"]}')
    if f.get('性别'):
        parts.append(f'- 性别: {f["性别"]}')
    if f.get('年龄'):
        parts.append(f'- 年龄: {f["年龄"]}')
    if f.get('身高'):
        parts.append(f'- 身高: {f["身高"]}')
    if f.get('头发颜色'):
        parts.append(f'- 发色: {f["头发颜色"]}')
    if f.get('眼睛颜色'):
        parts.append(f'- 瞳色: {f["眼睛颜色"]}')
    if f.get('职业'):
        parts.append(f'- 职业: {f["职业"]}')
    if f.get('班级'):
        parts.append(f'- 班级: {f["班级"]}')
    if f.get('生日'):
        parts.append(f'- 生日: {f["生日"]}')
    if f.get('日语配音演员'):
        parts.append(f'- 日语配音: {f["日语配音演员"]}')
    if f.get('中文配音演员'):
        parts.append(f'- 中文配音: {f["中文配音演员"]}')
    if f.get('英语配音演员'):
        parts.append(f'- 英语配音: {f["英语配音演员"]}')
    if f.get('亲属'):
        parts.append(f'- 亲属: {f["亲属"]}')
    parts.append('')

    if item['intro']:
        parts.append('【角色简介】')
        parts.append(item['intro'])
        parts.append('')

    if item['appearance']:
        parts.append('【外貌】')
        parts.append(item['appearance'])
        parts.append('')

    if item['personality']:
        parts.append('【人格 / 性格】')
        parts.append(item['personality'])
        parts.append('')

    if item['relations']:
        parts.append('【人际关系】')
        for r in item['relations']:
            parts.append(f'- {r["name"]}: {r["desc"] or "(wiki 未填写详情)"}')
        parts.append('')

    if item['trivia']:
        parts.append('【琐事 / 趣闻】')
        parts.append(item['trivia'])
        parts.append('')

    parts.append('【任务流程(内部思考,不输出)】')
    parts.append('1. 候选:基于以上资料,设计 6-7 个候选问题,每个问题的答案**必须能在以上文本里直接找到原文**:')
    parts.append('   - 人格类:问人格/性格描述中明确写出的特征')
    parts.append('   - 关系类:问关系章节中明确列出的对象与状态(只有关系章节非空才出)')
    parts.append('   - 外貌类:问外貌章节明确描述的特征(发色/瞳色/服装等)')
    parts.append('   - 琐事类:问琐事章节中的具体趣闻')
    parts.append('   - 元数据类:问配音/班级/年龄/亲属等 infobox 字段')
    parts.append('2. 配额:5 个 QA 中**至少 3 个必须基于人格/关系/外貌/琐事**(高差异化),')
    parts.append('   元数据类(配音/班级/年龄/发色等)不超过 2 个')
    parts.append('   例外:若高差异化字段全部为空,可降为纯元数据 QA,但至少穷尽所有非空字段')
    parts.append('3. 自检:对每个候选问"答案的关键信息能在哪个字段找到?";找不到的直接删除')
    parts.append('4. 多样化:剩下的候选中,优先保留覆盖不同侧面的;同类型保留 1 个')
    parts.append('5. 输出:最多保留 5 个(若资料稀薄,只输出 1-2 个也可接受,但至少 1 个)')
    parts.append('')
    parts.append('【硬约束】')
    parts.append('- 答案只能是上述文本的原话或直接转述,不允许跨字段推测、综合、归纳')
    parts.append('- 禁止"体现了..."/"展现了..."/"暗示..."等隐含推断措辞')
    parts.append('- 若发现某候选问题答案不在文本里,**直接删该问题**,不要改成"未提及"')
    parts.append('- 关系字段标"(wiki 未填写详情)"时,不要出该关系的具体内容问题')
    parts.append(anti_tautology_block('本角色页'))
    parts.append('**【Self-contained 硬约束 - 极其重要】**')
    parts.append('每个问题必须自包含,不依赖任何外部上下文即可被独立理解:')
    parts.append('- 禁止使用"她/他/这个角色/该角色/主角"等代词指代')
    parts.append(f'- 必须用【角色名】作为角色标识:**{name}**')
    parts.append(f'  示例(本角色): "{name}的人格特征是什么?"')
    parts.append('- 答案也要避免代词:"他/她/这/那"必须改成具体角色名或对象')
    parts.append('')
    parts.append('【输出格式】(只输出最终保留的 QA,不要输出候选和自检过程)')
    for i in range(1, 6):
        parts.append(f'Q{i}: ...')
        parts.append(f'A{i}: ...')
        parts.append('')
    parts.append('(若不足 5 个,只输出能通过自检的数量,从 Q1 顺延;不要凑数)')
    return '\n'.join(parts)


def template_qa(item: dict) -> list:
    f = item['fields']
    name = f.get('名称', item['title'])
    out = []
    if f.get('日语配音演员'):
        out.append((f'{name}的日语配音演员是谁?', f['日语配音演员']))
    if f.get('班级'):
        out.append((f'{name}属于哪个班级?', f['班级']))
    if f.get('性别'):
        out.append((f'{name}的性别是?', f['性别']))
    return out


def decontextualize(text: str, item: dict) -> str:
    f = item['fields']
    name = f.get('名称', item['title'])
    aliases = [a.strip() for a in re.split(r'[、,，]', f.get('别称', '')) if a.strip()]

    out = re.sub(r'(这个角色|该角色|主角|她|他|此人|其)(?=[，。、的之在是])',
                 name, text)

    for alias in aliases:
        if alias and alias != name:
            out = out.replace(f'「{alias}」', f'「{name}」')
    return out


def main():
    parser = argparse.ArgumentParser(description='Character QA pipeline (14 pages).')
    parser.add_argument('--max', type=int, default=0,
                        help='Max characters to process (0 = all 14)')
    parser.add_argument('--delay', type=float, default=0.5)
    parser.add_argument('--reset', action='store_true')
    args = parser.parse_args()

    if args.reset:
        cache_dir = REPO_ROOT / 'output' / '.cache'
        for p in [cache_dir / 'character.jsonl',
                  cache_dir / 'character.progress.json',
                  cache_dir / 'character.errors.json']:
            if p.exists():
                p.unlink()
        print('>> --reset: cleared character output', flush=True)

    print('>> loading dump...', flush=True)
    contents, _, contribs_with_years, _ = load_dump(DUMP_DIR / 'ns0.xml')
    char_dict = collect_characters(contents, contributors_by_page=contribs_with_years)
    items = [{'title': t, **v} for t, v in char_dict.items()]
    items.sort(key=lambda x: x['title'])
    print(f'   characters={len(items)}', flush=True)

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
        output_subdir='character',
        delay=args.delay,
        max_items=args.max,
        item_id_fn=lambda c: c['fields'].get('名称', c['title']),
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
