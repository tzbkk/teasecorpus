"""Edge-case test runner: hand-picked hardest samples per page type.

Outputs a markdown report to /tmp/opencode/edge_tests_report.md for review.
"""
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from wiki_parser import (
    load_dump, make_resolver, collect_chapters, collect_characters,
    collect_episodes, collect_music, collect_volumes, collect_seasons,
    collect_movies,
)
from llm_client import (
    load_env, require_env, call_llm, parse_qa_output, filter_tautological,
)

import chapter_qa
import character_qa
import episode_qa
import season_qa
import movie_qa
import music_qa
import volume_qa


REPO_ROOT = Path(__file__).resolve().parent.parent
DUMP_DIR = REPO_ROOT / 'wikidump'
REPORT_PATH = Path('/tmp/opencode/edge_tests_report.md')


CHAPTER_TITLES = [
    '漫画第10章',
    '漫画第107章',
    '漫画第17.5章',
    '明天星期六第1章',
    '原高木漫画第52章',
]
CHARACTER_TITLES = ['高木', '真野', '日日野美奈', '田边老师']
EPISODE_TITLES = ['动画第一季/OVA', '动画第一季/第1集', '动画第一季/第3集']
MUSIC_TITLES = ['Over Drive', 'STARS', '上午11点']
VOLUME_TITLES = ['明天星期六第1卷', '原高木漫画第1卷', '漫画第16卷']


def run_chapter(chapters_by_title, resolve_name, character_pages, env):
    rows = []
    for title in CHAPTER_TITLES:
        if title not in chapters_by_title:
            rows.append((title, 'NOT FOUND', [], '(no data)'))
            continue
        ch = chapters_by_title[title]
        ib = ch['infobox']
        notes = []
        if not ch['summary']:
            notes.append('no-summary(template)')
        if '.' in title.split('第')[-1].replace('章', ''):
            notes.append('decimal-no')
        if len(ch['characters']) >= 6:
            notes.append(f'{len(ch["characters"])}-chars')
        if ch['trivia']:
            notes.append('has-trivia')
        if title.startswith('明天星期六'):
            notes.append('ashita-series(prefix-risk)')
        if title.startswith('原高木'):
            notes.append('moto-series')

        if not ch['summary']:
            qa_pairs = chapter_qa.template_qa_for_no_summary(ch)
            rows.append((title, 'templated', qa_pairs, ', '.join(notes)))
            continue

        prompt = chapter_qa.build_user_prompt(ch, resolve_name, character_pages)
        result = call_llm(env, chapter_qa.SYSTEM, prompt)
        if 'error' in result:
            rows.append((title, f'LLM-ERROR: {result["error"][:80]}', [], ', '.join(notes)))
            continue
        output = result.get('choices', [{}])[0].get('message', {}).get('content', '')
        output = chapter_qa.decontextualize_qa(output, ch)
        qa_pairs = parse_qa_output(output)
        rows.append((title, 'llm', qa_pairs, ', '.join(notes)))
        time.sleep(0.5)
    return rows


def run_simple(build_prompt_fn, decontext_fn, system, items_by_title, titles, type_name):
    env = load_env()
    require_env(env, 'LLM_BASE_URL', 'LLM_MODEL', 'LLM_API_KEY')
    rows = []
    for title in titles:
        if title not in items_by_title:
            rows.append((title, 'NOT FOUND', [], '(no data)'))
            continue
        item = items_by_title[title]
        prompt = build_prompt_fn(item)
        if prompt is None:
            rows.append((title, 'NO-PROMPT', [], ''))
            continue
        result = call_llm(env, system, prompt)
        if 'error' in result:
            rows.append((title, f'LLM-ERROR: {result["error"][:80]}', [], ''))
            continue
        output = result.get('choices', [{}])[0].get('message', {}).get('content', '')
        if not output:
            finish = result.get('choices', [{}])[0].get('finish_reason', '?')
            rows.append((title, f'EMPTY-CONTENT (finish={finish})', [], ''))
            continue
        output = decontext_fn(output, item)
        qa_pairs = parse_qa_output(output)
        pre = len(qa_pairs)
        qa_pairs = filter_tautological(qa_pairs, title)
        dropped = pre - len(qa_pairs)
        note = type_name + (f', filtered {dropped}' if dropped else '')
        rows.append((title, 'llm', qa_pairs, note))
        time.sleep(0.5)
    return rows


def run_template_only(template_fn, items_by_title, titles, type_name):
    rows = []
    for title in titles:
        if title not in items_by_title:
            rows.append((title, 'NOT FOUND', [], '(no data)'))
            continue
        item = items_by_title[title]
        qa_pairs = template_fn(item)
        rows.append((title, 'templated', qa_pairs, type_name))
    return rows


def write_section(md, type_name, rows):
    md.append(f'\n## {type_name}\n')
    for title, mode, qa_pairs, notes in rows:
        md.append(f'### {title}')
        md.append(f'- mode: `{mode}`  | notes: {notes}')
        if not qa_pairs:
            md.append('- (no QA pairs)')
        for i, (q, a) in enumerate(qa_pairs, 1):
            md.append(f'- **Q{i}**: {q}')
            md.append(f'  - **A{i}**: {a}')
        md.append('')


def main():
    print('>> loading dump...', flush=True)
    contents, redirect_map = load_dump(DUMP_DIR / 'ns0.xml')
    resolve_name = make_resolver(redirect_map)

    chapters = collect_chapters(contents)
    chapters_by = {c['title']: c for c in chapters}
    characters = collect_characters(contents)
    characters_by = {t: {'title': t, **v} for t, v in characters.items()}
    episodes = collect_episodes(contents)
    episodes_by = {e['title']: e for e in episodes}
    music = collect_music(contents)
    music_by = {m['title']: m for m in music}
    volumes = collect_volumes(contents)
    volumes_by = {v['title']: v for v in volumes}
    seasons = collect_seasons(contents)
    seasons_by = {s['title']: s for s in seasons}
    movies = collect_movies(contents)
    movies_by = {m['title']: m for m in movies}

    env = load_env()
    require_env(env, 'LLM_BASE_URL', 'LLM_MODEL', 'LLM_API_KEY')

    md = ['# Edge Tests Report', '',
          f'Generated: {time.strftime("%Y-%m-%d %H:%M:%S")}', '',
          'Hand-picked hardest samples per page type. Each section shows',
          'the QA pairs produced so a human can verify quality.', '']

    md.append(f'\n---\n')
    rows = run_chapter(chapters_by, resolve_name, characters, env)
    write_section(md, 'chapter', rows)

    rows = run_simple(character_qa.build_user_prompt,
                      character_qa.decontextualize,
                      character_qa.SYSTEM,
                      characters_by, CHARACTER_TITLES, 'character')
    write_section(md, 'character', rows)

    rows = run_simple(episode_qa.build_user_prompt,
                      episode_qa.decontextualize,
                      episode_qa.SYSTEM,
                      episodes_by, EPISODE_TITLES, 'episode')
    write_section(md, 'episode', rows)

    rows = run_template_only(music_qa.template_qa, music_by, MUSIC_TITLES, 'music')
    write_section(md, 'music', rows)

    rows = run_template_only(volume_qa.template_qa, volumes_by, VOLUME_TITLES, 'volume')
    write_section(md, 'volume', rows)

    rows = run_simple(season_qa.build_user_prompt,
                      season_qa.decontextualize,
                      season_qa.SYSTEM,
                      seasons_by, list(seasons_by.keys()), 'season')
    write_section(md, 'season', rows)

    rows = run_simple(movie_qa.build_user_prompt,
                      movie_qa.decontextualize,
                      movie_qa.SYSTEM,
                      movies_by, list(movies_by.keys()), 'movie')
    write_section(md, 'movie', rows)

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text('\n'.join(md), encoding='utf-8')
    print(f'\n>> report: {REPORT_PATH}', flush=True)
    print(f'   {REPORT_PATH.stat().st_size} bytes', flush=True)


if __name__ == '__main__':
    main()
