# Pipeline

## 总览

```
                  ┌─────────────────┐
                  │  download_dump   │  ← Fandom API
                  │  update_dump     │
                  └────────┬────────┘
                           │ ns0.xml + Project.xml
                  ┌────────▼────────┐
                  │  wiki_parser.py  │
                  │  load_dump()     │
                  │  collect_*()     │
                  └────────┬────────┘
                           │ list[dict] items
                  ┌────────▼────────┐
                  │  llm_client.py   │
                  │  call_llm()      │
                  │  run_pipeline()  │
                  └────────┬────────┘
                           │ ChatML JSONL
                  ┌────────▼────────┐
                  │  merge_outputs   │
                  └─────────────────┘
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
contents, redirect_map = load_dump('wikidump/ns0.xml')

# 按类收集
chapters = collect_chapters(contents)       # 漫画第N章
volumes = collect_volumes(contents)         # 漫画第N卷
characters = collect_characters(contents)   # 角色页面
episodes = collect_episodes(contents)       # 剧集页面
music_items = collect_music(contents)       # 音乐页面
seasons = collect_seasons(contents)         # 季度页面
```

返回的 item dict 结构:

```python
{
    'title': '漫画第10章',
    'text': '完整的 wikitext',
    'infobox': {...},          # 信息框字段
    'sections': [...],         # 页面段落
    'summary': '...',          # 首段摘要
    'categories': [...],       # 分类标签
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
- 断点续传: 每 3 item flush 到磁盘，msync 保证数据安全
- 错误恢复: 单页失败不影响其他页
- 空 QA 后备: LLM 失败/空输出时走 `build_template_qa()`

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

**`merge_outputs.py`**: 扫描 `output/wiki_sft/{type}/` 下的 `data.jsonl`，合并为 `output/wiki_sft/all_data.jsonl`。

## 边界测试

**`edge_tests.py`**: 22 hard samples（含特殊模板、段节、嵌套结构等），涵盖所有页面类型的边缘情况。每个 pipeline 生产脚本都可通过 `--max` 参数小批量验证:
