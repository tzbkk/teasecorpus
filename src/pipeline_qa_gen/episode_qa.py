"""Episode page QA pipeline (37 pages, LLM-driven).

Each episode page yields ~4-5 QA pairs focused on segment-level plot
descriptions (high differentiation value) plus at most 2 metadata QA
(adapted manga chapters, OP/ED, airdate).
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # src/

from wiki_parser import load_dump, collect_episodes
from llm_client import run_pipeline, anti_tautology_block


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DUMP_DIR = REPO_ROOT / 'wikidump'

SYSTEM = ('你是《擅长捉弄的高木同学》wiki 知识助手。你只产出能从提供的剧集资料里'
          '直接找到答案的 QA 对,严格避免生成你无法回答的问题,'
          '且所有问题必须自包含(不依赖上下文代词)。')


def build_user_prompt(item: dict) -> str:
    f = item['fields']
    title = item['title']
    series = f.get('系列', '')
    ep_no = f.get('剧集号', '')
    ep_ref = f'{title}' if not ep_no else f'{title}(即{series}第{ep_no}集)'

    parts = [f'基于以下剧集完整资料产出最多 5 个 QA 对。\n']

    parts.append('【剧集元数据】')
    parts.append(f'- 完整剧集标题(必须用作问题中的剧集标识): {title}')
    if series:
        parts.append(f'- 所属动画系列: {series}')
    if ep_no:
        parts.append(f'- 剧集号: 第 {ep_no} 集')
    if f.get('播出日期'):
        parts.append(f'- 播出日期: {f["播出日期"]}')
    if f.get('改编漫画'):
        parts.append(f'- 改编自漫画: {f["改编漫画"]}')
    if f.get('片头曲'):
        parts.append(f'- 片头曲: {f["片头曲"]}')
    if f.get('片尾曲'):
        parts.append(f'- 片尾曲: {f["片尾曲"]}')
    if f.get('插曲'):
        parts.append(f'- 插曲: {f["插曲"]}')
    if f.get('上一集'):
        parts.append(f'- 上一集: {f["上一集"]}')
    if f.get('下一集'):
        parts.append(f'- 下一集: {f["下一集"]}')
    parts.append('')

    if item['intro']:
        parts.append('【剧集简介】')
        parts.append(item['intro'])
        parts.append('')

    if item['characters']:
        parts.append('【出场角色】')
        parts.append('、'.join(item['characters']))
        parts.append('')

    if item['segments']:
        parts.append('【本集片段(每段是独立剧情)】')
        for seg in item['segments']:
            parts.append(f'### 片段「{seg["name"]}」')
            parts.append(seg['desc'] or '(wiki 未填写片段详情)')
            parts.append('')
        parts.append('')

    parts.append('【任务流程(内部思考,不输出)】')
    parts.append('1. 候选:基于以上资料,设计 6-7 个候选问题,每个问题的答案**必须能在以上文本里直接找到原文**:')
    parts.append('   - 片段剧情类:针对每个片段问"该片段中发生的事件/角色行为/对话"')
    parts.append('   - 改编类:问改编自哪一章漫画')
    parts.append('   - 音乐类:问片头曲/片尾曲/插曲')
    parts.append('   - 元数据类:问播出日期/上一集/下一集')
    parts.append('2. 配额:5 个 QA 中**至少 3 个必须基于【本集片段】**(剧情问答是核心价值),')
    parts.append('   元数据类(播出日期/改编漫画/片头片尾曲等)不超过 2 个')
    parts.append('   例外:若无片段或片段无详情,可降为元数据 QA,但至少穷尽所有非空字段')
    parts.append('3. 自检:对每个候选问"答案的关键信息能在哪个字段找到?";找不到的直接删除')
    parts.append('4. 多样化:片段 QA 应覆盖不同片段,不要集中在同一片段;同片段最多 2 个 QA')
    parts.append('5. 输出:最多保留 5 个(若资料稀薄,只输出 1-2 个也可接受,但至少 1 个)')
    parts.append('')
    parts.append('【硬约束】')
    parts.append('- 答案只能是上述文本的原话或直接转述,不允许跨字段推测、综合、归纳')
    parts.append('- 禁止"体现了..."/"展现了..."/"暗示..."等隐含推断措辞')
    parts.append('- 若发现某候选问题答案不在文本里,**直接删该问题**,不要改成"未提及"')
    parts.append('- 片段标"(wiki 未填写详情)"时,不要出该片段具体内容问题')
    parts.append(anti_tautology_block('本集'))
    parts.append('**【Self-contained 硬约束 - 极其重要】**')
    parts.append('每个问题必须自包含,不依赖任何外部上下文即可被独立理解:')
    parts.append('- 禁止使用"本集/这一集/该集/this episode"等代词指代')
    parts.append(f'- 必须用【完整剧集标题】作为剧集标识:**{title}**')
    parts.append(f'  示例(本集): "在{title}中, X 做了什么?"')
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
    title = item['title']
    out = []
    if f.get('播出日期'):
        out.append((f'{title}的播出日期是?', f['播出日期']))
    if f.get('改编漫画'):
        out.append((f'{title}改编自漫画的哪一章?', f['改编漫画']))
    if f.get('片尾曲'):
        out.append((f'{title}的片尾曲是什么?', f['片尾曲']))
    return out


def decontextualize(text: str, item: dict) -> str:
    f = item['fields']
    title = item['title']
    ep_no = f.get('剧集号', '')
    series = f.get('系列', '')
    full_ref = title
    alt_ref = f'{series}第{ep_no}集' if series and ep_no else None

    out = re.sub(r'(本集|这一集|该集|此集|this episode)', full_ref, text, flags=re.IGNORECASE)
    if alt_ref and alt_ref in out:
        out = out.replace(alt_ref, full_ref)
    return out


def main():
    parser = argparse.ArgumentParser(description='Episode QA pipeline (37 pages).')
    parser.add_argument('--max', type=int, default=0,
                        help='Max episodes to process (0 = all 37)')
    parser.add_argument('--delay', type=float, default=0.5)
    parser.add_argument('--reset', action='store_true')
    args = parser.parse_args()

    if args.reset:
        out_dir = REPO_ROOT / 'output' / 'wiki_sft' / 'episode'
        for p in [out_dir / 'data.jsonl', out_dir / '.progress.json', out_dir / '.errors.json']:
            if p.exists():
                p.unlink()
        print('>> --reset: cleared episode output', flush=True)

    print('>> loading dump...', flush=True)
    contents, _ = load_dump(DUMP_DIR / 'ns0.xml')
    items = collect_episodes(contents)
    print(f'   episodes={len(items)}', flush=True)

    run_pipeline(
        items=items,
        build_prompt=build_user_prompt,
        build_template_qa=template_qa,
        decontextualize=decontextualize,
        system=SYSTEM,
        source_label='wikidump/ns0.xml',
        output_subdir='episode',
        delay=args.delay,
        max_items=args.max,
        item_id_fn=lambda e: e['title'],
    )


if __name__ == '__main__':
    main()
