# Pipeline

## 总览

```
download_dump.py          Fandom API → wikidump/*.xml
        ↓
wiki_parser.py            XML → 结构化 items(含 contributors + timestamps)
        ↓
setup_ob.py (一次性)      contributors → .ob/authors/ + .ob/sections/
        ↓
pipeline_qa_gen/*.py      LLM / template → output/.cache/{type}.jsonl
        ↓                          ↓
                        ob.track(file='dataset.jsonl') → .ob/document-index/
        ↓
merge_outputs.py          output/.cache/*.jsonl → dataset.jsonl (字节级拼接)
```

## 预处理(preproc)

**`download_dump.py`**: 从 Fandom wiki 下载完整 XML dump。

- 走 `prop=revisions` API，包含完整 revision history
- 默认命名空间: 0 (main) + 4 (project)
- 输出: `wikidump/ns0.xml` + `wikidump/<project_name>.xml`
- 断点续传: `.progress.json` 记录进度，中断后可续

**`update_dump.py`**: 增量更新已有 dump。

- 基于 `list=recentchanges` API + revision ID 高水位
- 产出独立 delta XML + 删除清单
- 不修改原全量文件

## 解析(parser)

**`wiki_parser.py`**: 共享的 MediaWiki XML 解析器。

核心函数:

```python
# 加载 dump
contents, redirect_map, contribs_with_years, contributor_ids = load_dump('wikidump/ns0.xml')

# 从指定 dump 提取单个 page(用于 cherry-pick 译名表)
text, contribs_with_years, contrib_ids = load_cherry_pick_page(
    'wikidump/擅长捉弄的高木同学wiki.xml',
    page_title='擅长捉弄的高木同学wiki:漫画标题译名表',
)

# 按类收集(可接受 contributors_by_page=None kwarg)
chapters = collect_chapters(contents, contributors_by_page=contribs_with_years)       # 漫画第N章
volumes = collect_volumes(contents, contributors_by_page=contribs_with_years)         # 漫画第N卷
characters = collect_characters(contents, contributors_by_page=contribs_with_years)   # 角色页面
episodes = collect_episodes(contents, contributors_by_page=contribs_with_years)       # 剧集页面
music_items = collect_music(contents, contributors_by_page=contribs_with_years)       # 音乐页面
seasons = collect_seasons(contents, contributors_by_page=contribs_with_years)         # 季度页面
```

**`load_dump` 返回 4-tuple**:
- `contents`: `list[(title, text)]` — 非重定向页面的标题和文本
- `redirect_map`: `dict[src_title: target_title]` — 重定向映射
- `contribs_with_years`: `dict[title, dict[contributor_name, list[timestamp]]]` — 每个 page 每个 contributor 的所有 revision timestamps
- `contributor_ids`: `dict[contributor_name, wiki_id_or_ip]` — contributor name 到稳定 ID 的映射

**`collect_*` 函数**现在接受可选的 `contributors_by_page=None` kwarg,当提供时会给每个 item 附加 `'contributors': set[name]` 字段。

返回的 item dict 结构(以章节为例):

```python
{
    'title': '漫画第10章',
    'infobox': {'章节数目': '10', '名称': '橡皮擦', '发布日期': '...', ...},
    'summary': '...',
    'characters': ['高木同学', '西片', ...],
    'location': '...',
    'trivia': '...',
    'quote': ('台词', '说话者'),  # or None
    'contributors': {'铁桶', 'Lunisha Kumina', ...},  # 仅当 contributors_by_page 传入时
}
```

## QA 生成

### LLM pipeline(章节/角色/剧集/季度/剧场版)

```
item → build_prompt() → call_llm() → parse_response() → filter_tautological() → QA pairs
                                                                    ↑
                             template_qa 后备                          ↓
                            (LLM 失败/空/格式错时)               to_chatml()
```

`run_pipeline()` 统一控制:
- 断点续传: 每 item 完成后 flush + fsync,保证数据安全
- 错误恢复: 单页失败不影响其他页
- 空 QA 后备: LLM 失败/空输出时走 `build_template_qa()`
- Provenance 追踪(可选): 通过 `source_extractor` + `track_fn` 参数接入 originblame

```python
run_pipeline(
    items, build_prompt, build_template_qa, decontextualize,
    system, output_subdir, delay, max_items, item_id_fn,
    source_extractor=None,  # optional: (item, qa_pair) -> list[section_hash] | None
    track_fn=None,          # optional: (chatml, file_path, section_hashes) -> None
)
```

分流清理:

```python
# 拼接时 decontextualize (remove "本章/本集/该角色")
qa_pairs = decontextualize(qa_pairs, item_title)

# 过滤同义反复(答案 = 标题或章节号)
qa_pairs = filter_tautological(qa_pairs, item_title)
```

### Template pipeline(音乐/卷)

纯模板，不走 LLM:

```python
if has_summary:
    template_qa_for_volume(item)    # 卷 QA
    template_qa_for_music(item)      # 音乐 QA
```

两种都有独立的 `main()` 函数，不走 `run_pipeline()`。

## 合并

**`merge_outputs.py`**: 扫描 `output/.cache/` 下的 `{type}.jsonl`,字节级拼接为仓库根的 `dataset.jsonl`。不修改内容,所以 line_hash 从 pipeline → dataset.jsonl 保持稳定。

## 边界测试

**`edge_tests.py`**: 22 hard samples（含特殊模板、段节、嵌套结构等），涵盖所有页面类型的边缘情况。多数 pipeline 脚本可通过 `--max` 参数小批量验证(`chapter_qa.py` 用 `--max-chapters`,`movie_qa.py` 无此参数)。

## Provenance (ob 集成)

Pipeline 支持 record-level provenance 追踪,通过 `source_extractor` + `track_fn` 参数接入 originblame。

**集成模式**:
- `chapter_qa.py` — 自定义 source_extractor,译名类 QA 含铁桶(译名表 section)
- `character/episode/season/movie_qa.py` — 标准 source_extractor via `make_source_extractor`
- `music/volume_qa.py` — template-only,在内层 loop 手动调 `track_chatml`

**line_hash 稳定性**: merge 字节级拼接不修改内容,line_hash 从 pipeline → dataset.jsonl 保持一致。

**数据流**:
```
setup_ob.py (一次性) → 注册 24 sections(23 contributors + 铁桶@译名表)
                       ↓
pipeline 运行时    → track(file='dataset.jsonl') 写 .ob/docidx.{pid} → clean_ob() merge
                       ↓
查询能力          → ob blame -d output/ output/dataset.jsonl N / ob show / ob revoke / ob purge
```

详见 [Provenance 详解](provenance.md)。
