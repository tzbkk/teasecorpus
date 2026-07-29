"""Shared LLM client + ChatML output + resume plumbing for QA pipelines."""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = REPO_ROOT / '.env'
CACHE_DIR = REPO_ROOT / 'output' / '.cache'


def load_env() -> dict:
    env = {}
    if not ENV_PATH.exists():
        return env
    for line in ENV_PATH.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        env[k.strip()] = v.strip()
    return env


def require_env(env: dict, *keys) -> None:
    missing = [k for k in keys if not env.get(k)]
    if missing:
        sys.exit(f'X missing in {ENV_PATH}: {", ".join(missing)}')


def call_llm(env: dict, system: str, user_prompt: str,
             temperature: float = 0.5, max_tokens: int = 6000) -> dict:
    base = env['LLM_BASE_URL'].rstrip('/')
    endpoint = base if '/chat/completions' in base else base + '/chat/completions'
    payload = {
        'model': env['LLM_MODEL'],
        'messages': [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': user_prompt},
        ],
        'temperature': temperature,
        'max_tokens': max_tokens,
    }
    data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(
        endpoint, data=data,
        headers={
            'Authorization': f'Bearer {env["LLM_API_KEY"]}',
            'Content-Type': 'application/json',
        },
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        return {'error': f'HTTP {e.code}: {e.read().decode("utf-8", "replace")[:300]}'}
    except Exception as e:
        return {'error': f'{e.__class__.__name__}: {e}'}


def parse_qa_output(output: str) -> list:
    """Parse 'Q1: ...\\nA1: ...\\n\\nQ2: ...' format into list of (q, a)."""
    pairs = []
    pat = r'Q(\d+):\s*(.+?)\s*\n+A\1:\s*(.+?)(?=\n+Q\d+:|\Z)'
    for m in re.finditer(pat, output, re.DOTALL):
        q = m.group(2).strip()
        a = m.group(3).strip()
        if q and a:
            pairs.append((q, a))
    return pairs


def filter_tautological(qa_pairs: list, context_id: str) -> list:
    """Drop QA pairs where the answer is trivially recoverable from the
    question itself or from the page title.

    Conservative: only filters when the cleaned answer (>=2 chars) is a
    contiguous substring of the cleaned question or title. Does NOT filter
    answers that merely *relate* to the question (which would over-trigger).
    """
    def clean(s: str) -> str:
        return re.sub(r'[《》。.,,!！?？\s第卷集章季]+', '', s)

    q_clean_cache = {}
    title_clean = clean(context_id)
    kept = []
    for q, a in qa_pairs:
        a_clean = clean(a)
        if len(a_clean) < 2:
            kept.append((q, a))
            continue
        if a_clean in title_clean:
            continue
        if q not in q_clean_cache:
            q_clean_cache[q] = clean(q)
        if a_clean in q_clean_cache[q]:
            continue
        kept.append((q, a))
    return kept


def anti_tautology_block(entity_label: str) -> str:
    """Standard prompt block enforcing 'question must not contain answer'."""
    return f"""
**【反 tautology 硬约束 - 极其重要】**
绝对禁止以下"问题里包含答案"或"答案可从问题/标题直接推断"的模式:

模式 1 - 问题里出现答案核心名词:
- 反例:Q: {entity_label}中,X 因为什么去神社避雨? A: 因为下雨
  问题已说"避雨",答案方向暴露
  修正:Q: {entity_label}中,X 因为什么不得不停下脚步? A: 突然下雨,去神社避雨

模式 2 - 利用 {entity_label} 标题作为答案线索:
- 反例:Q: {entity_label}《2年生》中,X 升到了几年级? A: 二年级
  标题《2年生》直接提示答案"二年级"
  修正:删除此类问题,只问正文中独立描述的内容

模式 3 - 答案复述问题里的修饰词:
- 反例:Q: 在"橡皮擦"片段中,X 借了什么? A: 橡皮擦
  问题里说"橡皮擦"片段,答案必然包含
  修正:Q: 在该片段中,X 向 Y 借了什么? A: 橡皮擦

自检流程(对每个候选 QA):
- 问"如果只看问题,能不能猜到答案或答案方向?" → 猜得到 → 删除
- 问"问题是否包含答案的核心名词?" → 包含 → 删除
- 问"答案是否就是标题里出现过的信息?" → 是 → 删除
"""


def to_chatml(system: str, q: str, a: str) -> dict:
    return {
        'messages': [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': q},
            {'role': 'assistant', 'content': a},
        ],
    }


def load_progress(path: Path) -> dict:
    if not path.exists():
        return {'last_completed_idx': -1, 'done_qa': 0}
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError:
        return {'last_completed_idx': -1, 'done_qa': 0}


def save_progress(path: Path, progress: dict) -> None:
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(progress, ensure_ascii=False), encoding='utf-8')
    tmp.replace(path)


def strip_incomplete_jsonl(path: Path) -> int:
    if not path.exists():
        return 0
    lines = path.read_text(encoding='utf-8').splitlines()
    valid = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            json.loads(line)
            valid.append(line)
        except json.JSONDecodeError:
            break
    path.write_text(('\n'.join(valid) + '\n') if valid else '', encoding='utf-8')
    return len(valid)


def run_pipeline(items, build_prompt, build_template_qa, decontextualize,
                 system: str, output_subdir: str,
                 delay: float, max_items: int, item_id_fn,
                 source_extractor=None, track_fn=None):
    """Generic pipeline runner.

    Args:
        items: list of parsed page dicts.
        build_prompt(item) -> str|None: returns LLM prompt, or None to use template path.
        build_template_qa(item) -> list[(q, a)]: fallback for no-LLM or sparse pages.
        decontextualize(text, item) -> str: post-process LLM output.
        system: system prompt.
        output_subdir: file stem under output/.cache/ (e.g. 'chapter' -> chapter.jsonl).
        delay: seconds between LLM calls.
        max_items: 0 = all.
        item_id_fn(item) -> str: human-readable id for logs/meta.
        source_extractor: optional callable
            `(item, qa_pair=None) -> list[str] | None` returning a list of
            section hashes the resulting ChatML row was derived from. Called
            PER QA pair (so extractors can vary source per question, e.g.
            chapter_qa's translation-table-aware extractor). When None or
            omitted, provenance tracking is disabled for this pipeline.
        track_fn: optional callable
            `(chatml, file_path, section_hashes) -> None` that calls
            `ob.track(...)` to record provenance. Only invoked when both
            `track_fn` and `source_extractor` are provided AND the extractor
            returned a non-empty list. Track exceptions are logged to err_log
            and never abort the pipeline.
    """
    env = load_env()
    require_env(env, 'LLM_BASE_URL', 'LLM_MODEL', 'LLM_API_KEY')
    print(f'>> LLM = {env["LLM_MODEL"]} @ {env["LLM_BASE_URL"]}', flush=True)

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    data_path = CACHE_DIR / f'{output_subdir}.jsonl'
    progress_path = CACHE_DIR / f'{output_subdir}.progress.json'
    err_path = CACHE_DIR / f'{output_subdir}.errors.json'

    valid_lines = strip_incomplete_jsonl(data_path)
    progress = load_progress(progress_path)
    last_idx = progress.get('last_completed_idx', -1)
    done_qa = progress.get('done_qa', valid_lines)

    total = len(items) if max_items == 0 else min(max_items, len(items))
    print(f'>> pipeline: {total} items, resuming from idx {last_idx + 1}, '
          f'{done_qa} QA in {data_path.name}', flush=True)

    err_log = []
    t0 = time.time()

    with open(data_path, 'a', encoding='utf-8') as f_out:
        for idx in range(last_idx + 1, total):
            item = items[idx]
            item_id = item_id_fn(item)
            qa_pairs = []
            mode = ''

            prompt = build_prompt(item)
            if prompt is None:
                qa_pairs = build_template_qa(item)
                mode = 'templated'
            else:
                result = call_llm(env, system, prompt)
                if 'error' in result:
                    err_log.append({'idx': idx, 'id': item_id, 'error': result['error']})
                    print(f'  [{idx + 1}/{total}] X {item_id}: {result["error"][:120]}',
                          flush=True)
                    time.sleep(delay)
                    continue
                output = result.get('choices', [{}])[0].get('message', {}).get('content', '')
                output = decontextualize(output, item)
                qa_pairs = parse_qa_output(output)
                mode = 'llm'

            pre = len(qa_pairs)
            qa_pairs = filter_tautological(qa_pairs, item_id)
            dropped = pre - len(qa_pairs)

            for q, a in qa_pairs:
                chatml = to_chatml(system, q, a)
                f_out.write(json.dumps(chatml, ensure_ascii=False) + '\n')

                if source_extractor is not None and track_fn is not None:
                    source_hashes = source_extractor(item, (q, a))
                    if source_hashes:
                        try:
                            track_fn(chatml, data_path, source_hashes)
                        except Exception as e:
                            err_log.append({'idx': idx, 'id': item_id,
                                            'track_error': str(e)[:200]})
            f_out.flush()
            os.fsync(f_out.fileno())

            done_qa += len(qa_pairs)
            progress = {
                'last_completed_idx': idx,
                'done_qa': done_qa,
                'last_id': item_id,
                'timestamp': time.time(),
            }
            save_progress(progress_path, progress)

            elapsed = time.time() - t0
            rate = (idx - last_idx) / elapsed if elapsed > 0 else 0
            eta_min = (total - idx - 1) / rate / 60 if rate > 0 else 0
            drop_note = f' (filtered {dropped})' if dropped else ''
            print(f'  [{idx + 1}/{total}] {item_id} [{mode}] +{len(qa_pairs)}{drop_note} '
                  f'(total {done_qa}, ETA {eta_min:.1f}min)', flush=True)

            if mode == 'llm' and idx < total - 1:
                time.sleep(delay)

    if err_log:
        err_path.write_text(json.dumps(err_log, ensure_ascii=False, indent=2),
                            encoding='utf-8')
        print(f'\n!! {len(err_log)} items failed, see {err_path}', flush=True)

    print(f'\n>> done: {done_qa} QA in {data_path}', flush=True)
    print(f'   elapsed: {(time.time() - t0) / 60:.1f}min', flush=True)
