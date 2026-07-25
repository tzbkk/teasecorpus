"""Shared wiki dump parser for all QA pipelines."""
import re
from xml.etree import ElementTree as ET
from pathlib import Path

NS = '{http://www.mediawiki.org/xml/export-0.11/}'

# 'Wikipedia' intentionally absent: [[Wikipedia:xxx|yyy]] is an external
# reference whose display text 'yyy' is meaningful (e.g. director names).
# Listed prefixes are true interlanguage / file / category links whose
# display text carries no QA value — strip them entirely.
REMOVE_PREFIXES = (
    'en', 'vi', 'ja', 'de', 'fr', 'es', 'ko', 'ru', 'zh',
    'Category', 'category', '分类',
    'File', 'Image', '文件', '檔案',
    'Help', 'Template', 'Project', 'Special', 'Media',
)

# {{X|a|b|c}} -> last non-empty positional arg is the human-readable text.
# Unknown templates fall through to "delete entirely" in strip_markup.
DISPLAY_TEMPLATES = {
    '颜色', 'ISBN', 'Lang', 'Lj', 'lj', 'R', 'Ruby',
}


def strip_markup(s: str) -> str:
    if not s:
        return ''
    pat = r'\[\[(?:' + '|'.join(re.escape(p) for p in REMOVE_PREFIXES) + r')\s*:[^\]]*\]\]'
    s = re.sub(pat, '', s, flags=re.IGNORECASE)
    s = re.sub(r'\[\[([^\]|]+)\|([^\]]+)\]\]', r'\2', s)
    s = re.sub(r'\[\[([^\]]+)\]\]', r'\1', s)
    s = re.sub(r'<s>.*?</s>', '', s, flags=re.DOTALL)
    s = re.sub(r'</?[a-zA-Z]+[^>]*>', '', s)

    def resolve_template(m):
        body = m.group(1)
        parts = _split_template_args(body)
        name = parts[0].strip() if parts else ''
        if name in DISPLAY_TEMPLATES:
            for p in reversed(parts[1:]):
                if '=' in p:
                    p = p.split('=', 1)[-1]
                p = p.strip()
                if p:
                    return p
            return ''
        return ''

    # Iterate so nested templates like {{Lj|{{R|x|y}}}} resolve inside-out.
    for _ in range(6):
        new_s = re.sub(r'\{\{([^{}]*)\}\}', resolve_template, s)
        if new_s == s:
            break
        s = new_s

    s = re.sub(r"<ref[^>]*>.*?</ref>", '', s, flags=re.DOTALL)
    s = re.sub(r"<ref[^>]*/?>", '', s)
    s = re.sub(r"'{2,}", '', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def _split_template_args(body: str) -> list:
    """Split on top-level | only, respecting [[...]] nesting."""
    parts = []
    cur = []
    depth = 0
    i = 0
    while i < len(body):
        c = body[i]
        if c == '[' and i + 1 < len(body) and body[i + 1] == '[':
            depth += 1
            cur.append('[[')
            i += 2
            continue
        if c == ']' and i + 1 < len(body) and body[i + 1] == ']' and depth > 0:
            depth -= 1
            cur.append(']]')
            i += 2
            continue
        if c == '|' and depth == 0:
            parts.append(''.join(cur))
            cur = []
            i += 1
            continue
        cur.append(c)
        i += 1
    parts.append(''.join(cur))
    return parts


def parse_template_fields(body: str) -> dict:
    """Parse infobox body. A field's value spans lines until the next
    line matching `|key =` — required to capture multi-line values
    (e.g. episode 改编漫画 field listing multiple chapters)."""
    fields = {}
    lines = body.split('\n')
    i = 0
    while i < len(lines):
        line = lines[i]
        m = re.match(r'\s*\|\s*([^=]+?)\s*=\s*(.*)', line)
        if not m:
            i += 1
            continue
        key = m.group(1).strip()
        val_parts = [m.group(2)]
        j = i + 1
        while j < len(lines):
            nxt = lines[j]
            if re.match(r'\s*\|\s*[^=]+\s*=', nxt):
                break
            if nxt.strip().startswith('}}'):
                break
            val_parts.append(nxt)
            j += 1
        raw_val = '\n'.join(val_parts).strip()
        val = strip_markup(raw_val)
        if val:
            fields[key] = val
        i = j
    return fields


def parse_infobox(text: str, template_name: str) -> dict:
    pat = r'\{\{\s*' + template_name + r'\s*\n(.*?)\n\}\}'
    m = re.search(pat, text, re.DOTALL)
    if not m:
        return {}
    return parse_template_fields(m.group(1))


def parse_infobox_any(text: str, template_names) -> dict:
    for name in template_names:
        r = parse_infobox(text, name)
        if r:
            return r
    return {}


def get_section(text: str, name: str) -> str:
    pat = r'==\s*' + re.escape(name) + r'\s*==\s*\n(.*?)(?=\n==[^=]|\Z)'
    m = re.search(pat, text, re.DOTALL)
    return m.group(1).strip() if m else ''


def get_subsections(text: str) -> list:
    """Return [(name, body)] for level-3 === name === inside text."""
    out = []
    pat = r'===\s*(.+?)\s*===\s*\n(.*?)(?=\n===|\Z)'
    for m in re.finditer(pat, text, re.DOTALL):
        out.append((strip_markup(m.group(1)), m.group(2).strip()))
    return out


def parse_chars_list(chars_text: str) -> list:
    out = []
    seen = set()
    for line in chars_text.split('\n'):
        line = re.sub(r'<s>.*?</s>', '', line, flags=re.DOTALL)
        line = re.sub(r'</?[a-zA-Z]+[^>]*>', '', line)
        m = re.match(r'\s*\*\s*(.+)', line)
        if not m:
            continue
        rest = m.group(1).strip()
        links = re.findall(r'\[\[([^\]|]+)(?:\|([^\]]+))?\]\]', rest)
        if links:
            for t, alt in links:
                if ':' in t and not t.startswith('['):
                    continue
                name = alt or t
                if name not in seen:
                    seen.add(name)
                    out.append(name)
        elif rest and not rest.startswith('{{') and not rest.startswith('[['):
            if rest not in seen:
                seen.add(rest)
                out.append(rest)
    return out


def parse_quote(text: str):
    """Parse {{引用|台词|说话者}}. Returns (line, speaker) or None."""
    m = re.search(r'\{\{引用\|([^|]+)\|([^}]+)\}\}', text)
    if not m:
        return None
    return (strip_markup(m.group(1)), strip_markup(m.group(2)))


def _intro_after_infobox(text: str) -> str:
    m = re.search(r'\}\}\s*\n(.*?)(?=\n==|\Z)', text, re.DOTALL)
    return strip_markup(m.group(1)) if m else ''


CHAR_FIELD_ALIASES = {
    '名称': '名称', 'name': '名称',
    '别称': '别称', 'alias': '别称', 'aliases': '别称',
    '日文名': '日文名', 'japanese': '日文名',
    '罗马音': '罗马音', 'romaji': '罗马音',
    '性别': '性别', 'gender': '性别',
    '年龄': '年龄', 'age': '年龄',
    '身高': '身高', 'height': '身高',
    '体重': '体重', 'weight': '体重',
    '头发颜色': '头发颜色', 'hair': '头发颜色',
    '眼睛颜色': '眼睛颜色', 'eyes': '眼睛颜色',
    '职业': '职业', 'job': '职业', 'occupation': '职业',
    '班级': '班级', 'class': '班级',
    '生日': '生日', 'birthday': '生日',
    '配音演员': '日语配音演员', '日语配音演员': '日语配音演员',
    '中文配音演员': '中文配音演员',
    '英语配音演员': '英语配音演员',
    '状态': '状态', 'status': '状态',
    '亲属': '亲属', 'family': '亲属',
}


def normalize_char_fields(raw: dict) -> dict:
    return _normalize(raw, CHAR_FIELD_ALIASES)


EPISODE_FIELD_ALIASES = {
    '名称': '名称', 'name': '名称',
    '系列': '系列', 'season': '系列',
    '剧集': '剧集号', 'episode': '剧集号', '集数': '剧集号',
    '播出日期': '播出日期', 'date': '播出日期', '播放日期': '播出日期',
    '播出时间': '播出日期',
    '漫画': '改编漫画', 'manga': '改编漫画',
    '片头曲': '片头曲', 'opening': '片头曲', 'op': '片头曲',
    '片尾曲': '片尾曲', 'ending': '片尾曲', 'ed': '片尾曲',
    '插曲': '插曲', 'insert': '插曲',
    '上一集': '上一集', 'previous': '上一集',
    '下一集': '下一集', 'next': '下一集',
}


def normalize_episode_fields(raw: dict) -> dict:
    return _normalize(raw, EPISODE_FIELD_ALIASES)


VOLUME_FIELD_ALIASES = {
    '名称': '名称', 'name': '名称',
    '作者': '作者', 'author': '作者',
    '系列': '系列', 'series': '系列',
    '卷数': '卷数', 'volume': '卷数',
    '页数': '页数', 'pages': '页数',
    '发布日期': '发布日期', 'date': '发布日期', 'release': '发布日期',
    '日版发布日期': '日版发布日期',
    '台版发布日期': '台版发布日期',
    'ISBN': 'ISBN', 'isbn': 'ISBN',
    '日版ISBN': '日版ISBN',
    '台版ISBN': '台版ISBN',
    '上一卷': '上一卷', 'previous': '上一卷',
    '下一卷': '下一卷', 'next': '下一卷',
}


def normalize_volume_fields(raw: dict) -> dict:
    return _normalize(raw, VOLUME_FIELD_ALIASES)


SEASON_FIELD_ALIASES = {
    '名称': '名称', 'name': '名称',
    '导演': '导演', 'director': '导演',
    '编剧': '编剧', 'writer': '编剧',
    '音乐': '音乐', 'music': '音乐',
    '制作公司': '制作公司', 'studio': '制作公司',
    '集数': '集数', 'episodes': '集数',
    '播放时间': '播放时间', 'airdate': '播放时间',
    '播放状态': '播放状态', 'status': '播放状态',
    '原作': '原作', 'original': '原作',
    '作者': '作者', 'author': '作者',
    '上一季': '上一季', 'previous': '上一季',
    '下一季': '下一季', 'next': '下一季',
}


def normalize_season_fields(raw: dict) -> dict:
    return _normalize(raw, SEASON_FIELD_ALIASES)


MOVIE_FIELD_ALIASES = {
    'name': '名称',
    'japanese': '日文名',
    'romaji': '罗马音',
    'director': '导演',
    'writer': '编剧',
    'music': '音乐',
    'studio': '制作公司',
    'date': '上映日期',
    'status': '状态',
    'original': '原作',
    'original-author': '作者',
}


def normalize_movie_fields(raw: dict) -> dict:
    return _normalize(raw, MOVIE_FIELD_ALIASES)


MUSIC_FIELD_ALIASES = {
    '名称': '名称', 'name': '名称',
    '日文名': '日文名', 'japanese': '日文名',
    '罗马音': '罗马音', 'romaji': '罗马音',
    '演唱': '演唱', 'artist': '演唱', 'singer': '演唱',
    '作曲': '作曲', 'composer': '作曲',
    '作词': '作词', 'lyricist': '作词', 'lyrics': '作词',
    '编曲': '编曲', 'arranger': '编曲',
    '使用范围': '使用范围', 'usage': '使用范围',
    '发布日期': '发布日期', 'date': '发布日期', 'release': '发布日期',
    '上一首': '上一首', 'previous': '上一首',
    '下一首': '下一首', 'next': '下一首',
}


def normalize_music_fields(raw: dict) -> dict:
    return _normalize(raw, MUSIC_FIELD_ALIASES)


def _normalize(raw: dict, aliases: dict) -> dict:
    out = {}
    for k, v in raw.items():
        nk = aliases.get(k.lower(), k)
        if nk not in out:
            out[nk] = v
    return out


def load_dump(dump_path: Path):
    """Returns (contents, redirects): list of (title, text) and {src: target}."""
    pages_raw = []
    for event, elem in ET.iterparse(str(dump_path), events=('end',)):
        if elem.tag != NS + 'page':
            continue
        title = elem.findtext(NS + 'title') or ''
        revs = elem.findall(NS + 'revision')
        if revs:
            rev = max(revs, key=lambda r: int(r.findtext(NS + 'id') or 0))
            text = rev.findtext(NS + 'text') or ''
            pages_raw.append((title, text))
        elem.clear()

    redirect_map = {}
    for title, text in pages_raw:
        m = re.match(r'\s*#REDIRECT\s*\[\[([^\]|]+)(?:\|[^\]]+)?\]\]', text, re.IGNORECASE)
        if m:
            redirect_map[title] = m.group(1).strip()

    contents = [(t, tx) for t, tx in pages_raw
                if not re.match(r'\s*#REDIRECT', tx, re.IGNORECASE)]
    return contents, redirect_map


def make_resolver(redirect_map: dict):
    def resolve(name: str) -> str:
        seen = set()
        while name in redirect_map and name not in seen:
            seen.add(name)
            name = redirect_map[name]
        return name
    return resolve


def collect_chapters(contents):
    out = []
    for title, text in contents:
        if not re.match(r'^.+?第[\d.]+章$', title):
            continue
        ib = parse_infobox_any(text, ('章节资料', 'Infobox Chapter'))
        summary = strip_markup(get_section(text, '摘要'))
        chars_section = get_section(text, '出场角色') or get_section(text, '角色')
        characters = parse_chars_list(chars_section)
        location = strip_markup(get_section(text, '地点') or get_section(text, '位置'))
        trivia = strip_markup(get_section(text, '琐事'))
        quote = parse_quote(text)
        out.append({
            'title': title,
            'infobox': ib,
            'summary': summary,
            'characters': characters,
            'location': location,
            'trivia': trivia,
            'quote': quote,
        })
    out.sort(key=lambda c: c['title'])
    return out


def collect_characters(contents):
    """Returns {title: {fields, intro, appearance, personality, relations, trivia}}."""
    out = {}
    for title, text in contents:
        if re.match(r'\s*#REDIRECT', text, re.IGNORECASE):
            continue
        raw = parse_infobox_any(text, ('角色信息', r'Infobox\s+character'))
        if not raw:
            continue
        fields = normalize_char_fields(raw)
        if not fields:
            continue
        rel_section = get_section(text, '关系')
        relations = [{'name': n, 'desc': strip_markup(b)}
                     for n, b in get_subsections(rel_section)]
        out[title] = {
            'fields': fields,
            'intro': _intro_after_infobox(text),
            'appearance': strip_markup(get_section(text, '外貌')),
            'personality': strip_markup(get_section(text, '人格') or get_section(text, '性格')),
            'relations': relations,
            'trivia': strip_markup(get_section(text, '琐事')),
        }
    return out


def collect_episodes(contents):
    out = []
    for title, text in contents:
        raw = parse_infobox(text, '剧集信息')
        if not raw:
            continue
        fields = normalize_episode_fields(raw)
        chars = parse_chars_list(get_section(text, '出场角色'))
        segments = [{'name': n, 'desc': strip_markup(b)}
                    for n, b in get_subsections(get_section(text, '片段'))]
        out.append({
            'title': title,
            'fields': fields,
            'characters': chars,
            'segments': segments,
            'intro': _intro_after_infobox(text),
        })
    out.sort(key=lambda e: e['title'])
    return out


def collect_music(contents):
    out = []
    for title, text in contents:
        raw = parse_infobox(text, '音乐信息')
        if not raw:
            continue
        fields = normalize_music_fields(raw)
        out.append({
            'title': title,
            'fields': fields,
            'intro': _intro_after_infobox(text),
        })
    out.sort(key=lambda m: m['title'])
    return out


def collect_volumes(contents):
    out = []
    for title, text in contents:
        raw = parse_infobox(text, '卷资料')
        if not raw:
            continue
        fields = normalize_volume_fields(raw)
        out.append({
            'title': title,
            'fields': fields,
            'chapters': parse_chars_list(get_section(text, '章节')),
            'intro': _intro_after_infobox(text),
        })
    out.sort(key=lambda v: v['title'])
    return out


def collect_seasons(contents):
    out = []
    for title, text in contents:
        raw = parse_infobox(text, '动画资料')
        if not raw:
            continue
        fields = normalize_season_fields(raw)
        out.append({
            'title': title,
            'fields': fields,
            'synopsis': strip_markup(get_section(text, '内容简介') or get_section(text, '简介')),
        })
    out.sort(key=lambda s: s['title'])
    return out


def collect_movies(contents):
    out = []
    for title, text in contents:
        raw = parse_infobox_any(text, ('Infobox Movie', r'Infobox\s+film'))
        if not raw:
            continue
        fields = normalize_movie_fields(raw)
        syn_section = get_section(text, '简介')
        synopsis = ''
        if '<tabber>' in syn_section:
            zh_m = re.search(r'\|\-\|\s*中文版\s*=\s*(.*?)(?=\|\-\||</tabber>)',
                             syn_section, re.DOTALL)
            if zh_m:
                synopsis = strip_markup(
                    zh_m.group(1).replace('<poem>', '').replace('</poem>', ''))
        elif syn_section:
            synopsis = strip_markup(syn_section)

        release_dates = []
        rel_section = get_section(text, '上映地区及时间') or get_section(text, '上映')
        for line in rel_section.split('\n'):
            line = strip_markup(line)
            if line.startswith('*'):
                release_dates.append(line.lstrip('* ').strip())

        out.append({
            'title': title,
            'fields': fields,
            'intro': _intro_after_infobox(text),
            'synopsis': synopsis,
            'release_dates': release_dates,
        })
    return out
