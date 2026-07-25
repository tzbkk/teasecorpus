"""Chapter page QA pipeline (247 pages).

Generates ChatML SFT data from chapter pages by combining:
- LLM-driven QA for chapters with a non-empty summary (~187 pages)
- Templated fallback QA for chapters lacking a summary (~60 pages)
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # src/

from wiki_parser import (
    load_dump, make_resolver, collect_chapters, collect_characters,
)
from llm_client import run_pipeline, anti_tautology_block


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DUMP_DIR = REPO_ROOT / 'wikidump'

SYSTEM = ('你是《擅长捉弄的高木同学》wiki 知识助手。你只产出能从提供的字段文本里'
          '直接找到答案的 QA 对,严格避免生成你无法回答的问题,'
          '且所有问题必须自包含(不依赖上下文代词)。')


def build_user_prompt(ch: dict, resolve_name, character_pages) -> str:
    ib = ch['infobox']
    parts = ['基于以下章节完整信息产出最多 4 个 QA 对。\n']
    parts.append('【章节元数据】')
    parts.append(f'- 完整章节标题(必须用作问题中的章节标识): {ch["title"]}')
    if ib.get('名称'):
        parts.append(f'- 章节名: 《{ib["名称"]}》')
    if ib.get('日文名'):
        parts.append(f'- 日文名: {ib["日文名"]}')
    if ib.get('罗马音'):
        parts.append(f'- 罗马音: {ib["罗马音"]}')
    if ib.get('系列'):
        parts.append(f'- 系列: {ib["系列"]}')
    if ib.get('卷数'):
        parts.append(f'- 所属卷: {ib["卷数"]}')
    if ib.get('章节数目'):
        parts.append(f'- 章节号: 第 {ib["章节数目"]} 章')
    if ib.get('页数'):
        parts.append(f'- 页数: {ib["页数"]}')
    if ib.get('发布日期'):
        parts.append(f'- 发布日期: {ib["发布日期"]}')
    if ib.get('动画'):
        parts.append(f'- 改编动画: {ib["动画"]}')
    parts.append('')

    if ch['quote']:
        parts.append('【本章代表台词】(作者/编辑挑选的关键句)')
        parts.append(f'「{ch["quote"][0]}」 — {ch["quote"][1]}')
        parts.append('')

    parts.append('【本章摘要】(剧情概要)')
    parts.append(ch['summary'] if ch['summary'] else '(本章未填写摘要)')
    parts.append('')

    if ch['characters']:
        parts.append('【本章出场角色】')
        parts.append('、'.join(ch['characters']))
        parts.append('')

    char_bg_lines = []
    for cname in ch['characters'][:3]:
        resolved = resolve_name(cname)
        if resolved in character_pages:
            cp = character_pages[resolved]
            f = cp['fields']
            role_info = '/'.join(v for v in [
                f.get('性别', ''), f.get('年龄', ''), f.get('职业', '')
            ] if v)
            pers = cp['personality']
            if len(pers) > 200:
                pers = pers[:200] + '...'
            display_name = cname if cname == resolved else f'{cname}(→{resolved})'
            line = f'- {display_name}({role_info}): {pers}' if pers else f'- {display_name}({role_info}): wiki 未填写人格'
            char_bg_lines.append(line)
        else:
            char_bg_lines.append(f'- {cname}: (wiki 无独立角色页)')
    if char_bg_lines:
        parts.append('【关键角色背景知识】(仅当答案需要描述角色人格时可引用)')
        parts.extend(char_bg_lines)
        parts.append('')

    if ch['location']:
        parts.append('【本章地点】')
        parts.append(ch['location'])
        parts.append('')

    if ch['trivia']:
        parts.append('【本章琐事 / 幕后】')
        parts.append(ch['trivia'])
        parts.append('')

    parts.append('【任务流程(内部思考,不输出)】')
    parts.append('1. 候选:基于以上字段,设计 6 个候选问题,每个问题的答案**必须能在以上字段文本里直接找到原文**:')
    parts.append('   - 剧情事实类:问摘要中明确描述的事件、动作、对象')
    parts.append('   - 动机类:仅当摘要显式描述了角色动机时才出(摘要只写"X 做了 Y"但没说为什么 → 不出)')
    parts.append('   - 元数据类:问章节号/发布日期/卷/改编动画/日文名等(几乎都能答)')
    parts.append('   - 台词归属类:仅当有【本章代表台词】时出(谁说的)')
    parts.append('   - 互动模式类:仅当摘要描述了角色间具体互动时才出')
    parts.append('2. 配额:4 个 QA 中**至少 2 个必须基于【本章摘要】**(剧情事实/动机/互动/台词类),')
    parts.append('   元数据类(章节号/日期/卷/动画等)不超过 2 个')
    parts.append('   例外:若摘要稀薄到无法支撑 2 个非元数据 QA,可降为 1 个非元数据 + 3 元数据,但必须先穷尽非元数据尝试')
    parts.append('3. 自检:对每个候选问"答案的关键信息能在哪个字段找到?";找不到的直接删除,不要试图补救')
    parts.append('4. 多样化:剩下的候选中,优先保留覆盖不同侧面的;同类型保留 1 个')
    parts.append('5. 输出:最多保留 4 个(若信息稀薄,只输出 1-2 个也可接受,但至少 1 个)')
    parts.append('')
    parts.append('【硬约束】')
    parts.append('- 答案只能是上述字段文本的原话或直接转述,不允许跨字段推测、综合、归纳')
    parts.append('- 禁止"体现了..."/"展现了..."/"暗示..."/"由此推测..."等隐含推断措辞')
    parts.append('- 若发现某候选问题答案不在字段里,**直接删该问题**,不要改成"未提及"')
    parts.append('- 角色背景字段标注"(wiki 无独立角色页)"时,不要出依赖该角色背景的问题')
    parts.append(anti_tautology_block('本章'))
    parts.append('**【Self-contained 硬约束 - 极其重要】**')
    parts.append('每个问题必须自包含,不依赖任何外部上下文即可被独立理解:')
    parts.append('- 禁止使用"本章"、"这一章"、"这章"、"the chapter"等代词指代')
    parts.append(f'- 必须用【完整章节标题】作为章节标识:**{ch["title"]}**')
    full_ref = f'{ch["title"]}《{ib.get("名称","")}》' if ib.get('名称') else ch['title']
    parts.append(f'  推荐形式: "{full_ref}中, ..."')
    parts.append(f'  示例(本章节): "在{ch["title"]}中, X 做了什么?"')
    parts.append('- **严禁系列混淆**:')
    parts.append(f'  - 章节标题是 "{ch["title"]}",必须**原样使用**')
    parts.append(f'  - 不得改写为"漫画第N章"(除非该 title 本身以"漫画第"开头)')
    parts.append(f'  - 不得改写为其他系列前缀')
    parts.append('- 答案也要避免代词:"他/她/这/那"必须改成具体角色名或对象')
    parts.append('')
    parts.append('【输出格式】(只输出最终保留的 QA,不要输出候选和自检过程)')
    parts.append('Q1: ...')
    parts.append('A1: ...')
    parts.append('')
    parts.append('Q2: ...')
    parts.append('A2: ...')
    parts.append('')
    parts.append('Q3: ...')
    parts.append('A3: ...')
    parts.append('')
    parts.append('Q4: ...')
    parts.append('A4: ...')
    parts.append('')
    parts.append('(若不足 4 个,只输出能通过自检的数量,从 Q1 顺延;不要凑数)')
    return '\n'.join(parts)


def template_qa_for_no_summary(ch: dict) -> list:
    ib = ch['infobox']
    out = []
    title = ch['title']
    no = ib.get('章节数目', '')
    name = ib.get('名称', '')

    def add(q, a):
        a_clean = re.sub(r'[《》。.,,!！?？\s]+', '', a)
        title_clean = re.sub(r'[《》。.,,!！?？\s]+', '', title)
        if a_clean and len(a_clean) >= 2 and a_clean in title_clean:
            return
        if a_clean and len(a_clean) >= 2 and a_clean in re.sub(r'[《》。.,,!！?？\s]+', '', q):
            return
        out.append((q, a))

    if name and name not in title:
        add(f'{title}的本章名是什么?', f'《{name}》')
    if ib.get('卷数'):
        add(f'{title}收录在哪一卷?', ib['卷数'])
    if ib.get('发布日期'):
        add(f'{title}的发布日期是?', ib['发布日期'])
    if ib.get('动画'):
        add(f'{title}被改编为动画的哪一集?', ib['动画'])
    if ch['quote']:
        add(f'{title}的代表台词是谁说的?',
            f'{ch["quote"][1]}说了「{ch["quote"][0]}」')
    return out


def decontextualize_qa(text: str, ch: dict) -> str:
    ib = ch['infobox']
    title = ch['title']
    name = ib.get('名称', '').strip()
    no = ib.get('章节数目', '').strip()
    full_ref = f'{title}《{name}》' if name else title

    out = re.sub(r'(本章|这一章|这章|the chapter)', full_ref, text, flags=re.IGNORECASE)

    if no and not title.startswith('漫画第'):
        wrong_manga = f'漫画第{no}章'
        wrong_manga_named = f'漫画第{no}章《{name}》' if name else None

        if title not in out:
            if wrong_manga_named and wrong_manga_named in out:
                out = out.replace(wrong_manga_named, full_ref)
            elif wrong_manga in out:
                out = out.replace(wrong_manga, title)
    return out


def main():
    parser = argparse.ArgumentParser(description='Chapter QA pipeline (247 pages).')
    parser.add_argument('--max-chapters', type=int, default=0,
                        help='Max chapters to process (0 = all 247)')
    parser.add_argument('--delay', type=float, default=0.5,
                        help='Delay between LLM calls (seconds)')
    parser.add_argument('--reset', action='store_true',
                        help='Clear output and progress, start from scratch')
    args = parser.parse_args()

    if args.reset:
        out_dir = REPO_ROOT / 'output' / 'wiki_sft' / 'chapter'
        for p in [out_dir / 'data.jsonl', out_dir / '.progress.json', out_dir / '.errors.json']:
            if p.exists():
                p.unlink()
        print('>> --reset: cleared chapter output and progress', flush=True)

    print('>> loading dump...', flush=True)
    contents, redirect_map = load_dump(DUMP_DIR / 'ns0.xml')
    chapter_pages = collect_chapters(contents)
    character_pages = collect_characters(contents)
    resolve_name = make_resolver(redirect_map)
    print(f'   chapters={len(chapter_pages)} characters={len(character_pages)}', flush=True)

    def build_prompt(ch):
        if not ch['summary']:
            return None
        return build_user_prompt(ch, resolve_name, character_pages)

    run_pipeline(
        items=chapter_pages,
        build_prompt=build_prompt,
        build_template_qa=template_qa_for_no_summary,
        decontextualize=decontextualize_qa,
        system=SYSTEM,
        source_label='wikidump/ns0.xml',
        output_subdir='chapter',
        delay=args.delay,
        max_items=args.max_chapters,
        item_id_fn=lambda ch: ch['title'],
    )


if __name__ == '__main__':
    main()
