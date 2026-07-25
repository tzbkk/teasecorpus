# Provenance (ob 集成)

## 概览

teasecorpus 通过 [originblame](../rust-originblame) 实现每条 ChatML QA 的 record-level provenance 追踪,支持:

- **来源查询**: `ob blame` — 查询某条 QA 来自哪些 wiki contributors
- **作者撤销**: `ob revoke --email` — 标记某 author 的所有 contributions
- **物理清理**: `ob purge` — 删除已撤销的 records(可选 --dry-run 预览)

**设计目标**: 未来若某 contributor 的内容需移除(例如版权争议),可精确追踪并批量删除其所有衍生 QA,而不影响其他 valid records。

## 架构

```
output/
├── .ob/
│   ├── authors/               # 23 unique contributors(铁桶在 ns0 + 译名表两个 section 都出现)
│   ├── sections/              # 24 sections: ns0 × 23 + 译名表 × 1
│   ├── document-index/        # 每条 QA 的 line_hash + source 映射
│   └── teasecorpus_section_map.json  # cache: {(source, contributor): section_hash}
├── .cache/
│   └── {type}.jsonl           # 中间产物(.gitignore)
└── dataset.jsonl              # 成品数据集
```

### Sections 定义

| source_path | contributors | section 数量 | 用途 |
|-------------|--------------|--------------|------|
| `wikidump/ns0.xml` | 23 (21 users + 2 IPs) | 23 | QA 主源(所有 7 pipeline) |
| `wikidump/擅长捉弄的高木同学wiki.xml::漫画标题译名表` | 铁桶 | 1 | chapter_qa 译名类 QA |

每个 `(source_path, contributor)` 组合注册为一个 section,section_hash 用于 `track(source=[hashes])`。

## 设置流程

### 一次性初始化

```bash
python src/setup_ob.py
```

该脚本执行以下步骤:

1. **解析 ns0.xml contributors**:
   - 提取每个 page 的所有 `<revision>` 元素
   - 聚合每个 contributor 的所有 timestamps
   - 构建 `{contributor: (wiki_id, year_range_str)}` 映射

2. **cherry-pick 译名表**:
   - 从 `wikidump/擅长捉弄的高木同学wiki.xml` 提取 `漫画标题译名表` page
   - 解析该 page 的 contributors(仅铁桶)

3. **注册 authors + sections**:
   - 调用 `author_add(name=username, email={wiki_id}@teasecorpus.invalid)`
   - 调用 `register_section(path=source_path, authors=[name], year=year_range)`

4. **缓存 section_map**:
   - 保存到 `.ob/teasecorpus_section_map.json`
   - 格式: `[{"source": "...", "contributor": "...", "hash": "..."}, ...]`

**预期输出**:
```
ns0.xml: 23 unique contributors
  铁桶: id=32416701 email=32416701@teasecorpus.invalid year='2018-2026'
  Lunisha Kumina: id=55584564 email=55584564@teasecorpus.invalid year='2024-2026'
  ...
译名表: 铁桶 id=32416701 email=32416701@teasecorpus.invalid year='2019-2026'
registered 24 sections
  - ns0.xml: 23
  - 译名表: 1
```

### Author Email 设计

Email 格式: `{wiki_id}@teasecorpus.invalid`

- **wiki_id**: Fandom 全局稳定标识符(`<id>` 字段),IP 贡献者用 IP 本身
- **`.invalid` TLD**: RFC 6761 保留域名,保证 NXDOMAIN(不可送达)
- **用途**: `ob revoke --email` 的唯一 lookup key

示例:
- 铁桶: `32416701@teasecorpus.invalid`
- IP 贡献者: `1.2.3.4@teasecorpus.invalid`

### Year Range 字段

格式: `"YYYY"` 或 `"YYYY-YYYY"`

- 单年贡献: `"2020"`
- 多年贡献: `"2018-2026"`
- 空: `""`

由 `year_range(timestamps)` 函数计算,提取所有 revision timestamps 的年份去重排序。

示例:
```
(ns0.xml, 铁桶)        -> "2018-2026" (跨 9 个年份)
(ns0.xml, Tugiacat666) -> "2020" (单年)
(译名表, 铁桶)          -> "2019-2026"
```

## Section 覆盖策略

### ns0.xml (23 sections)

覆盖 ns0 命名空间的所有 408 pages,包括:

- 247 章节
- 14 角色
- 37 剧集
- 41 音乐
- 23 卷
- 3 季度
- 1 剧场版
- 22 unclassified

所有 23 contributors (21 users + 2 IPs) 都在 ns0.xml 有贡献。

### 译名表 (1 section)

Cherry-pick `擅长捉弄的高木同学wiki.xml` 中的 `漫画标题译名表` page,仅铁桶 1 人贡献。

**为什么 cherry-pick?**
- 译名表提供章节日文/中文/英文译名,是 chapter_qa 的增量数据源
- 其他 ns=4 pages(社群规则、元模板等)对 QA 无增量,已 spike 验证

## Page-level Attribution

我们选择 **page-level attribution**(而非 ob_util 的 chunk-level):

- **粒度**: 每个 page 的所有 contributors 合并为一个 source set
- **section 数量**: 24 个(23 ns0 + 1 译名表)
- **trade-off**: 更简单,但类型修正者和主要作者同权

**为什么不选 chunk-level?**
- chunk-level 用 git-diff 式 blame 将每行归因到最后修改者
- QA 级 provenance 不需要 line-level 精度
- chunk-level 会导致 sections 数量庞大(每 chunk × 每 contributor)

若未来需要 line-level 精度,可迁移到 ob_util chunk-level 模式。

## Pipeline 集成模式

**track 时 file 参数**: 固定为 `dataset.jsonl`(常量),不是中间文件路径。Rust blame 按 hash 查找忽略 file,但 ob show 显示记录里的 file 字段,用成品路径更清晰。

**line_hash 稳定性**: merge 字节级拼接不改内容,line_hash 从 pipeline → dataset.jsonl 保持一致,`ob blame -d output/ output/dataset.jsonl N` 直接可用。

### 1. chapter_qa.py (自定义模式)

**特点**: 译名类 QA 需包含译名表 section(铁桶)

```python
# 自定义 source_extractor
def _extract(item, qa_pair=None):
    contributors = item.get('contributors', set())
    hashes = [
        section_map[(NS0_PATH, c)]
        for c in contributors
        if (NS0_PATH, c) in section_map
    ]
    chap_id = item.get('infobox', {}).get('章节数目', '')
    if chap_id and chap_id in translation_table:
        # 有译名 → 附加译名表 section
        for (src, _contributor), h in section_map.items():
            if src == TRANSLATION_TABLE_PATH:
                hashes.append(h)
    return hashes

source_extractor = _extract
track_fn = track_chatml
```

### 2. character/episode/season/movie_qa.py (标准模式)

使用 `make_source_extractor` 辅助函数:

```python
source_extractor = make_source_extractor(
    section_map,
    source_path='wikidump/ns0.xml',
)
track_fn = track_chatml
```

### 3. music/volume_qa.py (手动模式)

Template-only,不走 `run_pipeline`,直接在内层 loop 调用 `track_chatml`:

```python
with open(data_path, 'a', encoding='utf-8') as f_out:
    for item in items:
        qa_pairs = template_qa_for_volume(item)
        for q, a in qa_pairs:
            chatml = to_chatml(system, q, a)
            f_out.write(json.dumps(chatml, ensure_ascii=False) + '\n')
            # 手动追踪
            if track_fn:
                source_hashes = source_extractor(item, (q, a))
                if source_hashes:
                    track_chatml(chatml, data_path, source_hashes)
```

### run_pipeline 参数

```python
run_pipeline(
    items, build_prompt, build_template_qa, decontextualize,
    system, output_subdir, delay, max_items, item_id_fn,
    source_extractor=None,  # (item, qa_pair) -> list[section_hash] | None
    track_fn=None,          # (chatml, file_path, section_hashes) -> None
)
```

**工作流**:
1. 每个 QA 写入 JSONL 后,调用 `source_extractor(item, (q, a))`
2. 若返回 non-empty list,调用 `track_fn(chatml, data_path, section_hashes)`
3. Track 失败记录到 `.errors.json`,不阻断 pipeline

## PID 文件生命周期

### 写入

`track()` 写入临时 PID 文件: `.ob/docidx.{pid}`

- 每次 `track()` 调用追加一条 entry(`(line_hash, file, sources)` 三元组)
- JSONL 与 PID 文件均按 item 节奏 flush(item 完成后 fsync JSONL)

### Merge

`clean_ob()` 合并所有 PID 文件到 manifest shards:

- **启动时调用**: 吸收上次崩溃留下的 PID 文件
- **结束时调用**: 确保查询立即可用
- **幂等性**: 无 PID 文件时 no-op

merge_outputs.py 跑完后,所有 records 的 file 字段都指向 `dataset.jsonl`,可在成品上直接 `ob blame`。

### 查询时机

必须在 `clean_ob()` 之后才能 `ob blame` / `ob show`:

```
pipeline 运行 → track() 写 PID → clean_ob() merge → ob blame 可用
```

### 防止冲突

每个 pipeline 启动 + 结束都调 `clean_ob()`:

- 启动时: 清理上次崩溃遗留
- 结束时: 确保本次数据立即可查

PID 文件冲突会 silently lose 数据,必须遵守此流程。

## 查询/撤销

### ob blame — 查询某条 QA 的来源

```bash
ob blame -d output/ output/dataset.jsonl 1
```

输出该 QA 的所有 section contributors。

### ob show — 查询某 author 的所有 records

```bash
ob show -d output/ --email "32416701@teasecorpus.invalid"
```

显示铁桶的所有 QA records(默认排除 revoked,加 `--revoked` 显示已撤销)。

### ob revoke — 撤销 author(toggle)

```bash
ob revoke -d output/ --email "32416701@teasecorpus.invalid"
```

标记铁桶 author.revoked=True,lazy cascade 到所有相关 sections + QA records。

- **toggle 模式**: 再次调用撤销 revoke(`--reverse` 恢复)
- **lazy cascade**: 写端只 tag,查询时自动过滤

### ob purge — 物理删除

```bash
ob purge -d output/ output/dataset.jsonl --dry-run  # 预览
ob purge -d output/ output/dataset.jsonl            # 执行
```

物理删除已 revoked 的 records from JSONL 文件。

**注意事项**:
- 必须先 `ob revoke` 才能 `ob purge`
- `--dry-run` 预览,防止误删
- 重跑 pipeline 前建议 `ob purge` 清理旧记录

### ob status — 统计

```bash
ob status -d output/
```

显示:
- Authors 数量
- Sections 数量
- Manifest entries 数量

## 故障排查

### "ob provenance: DISABLED (...)"

**原因**: `setup_ob.py` 未运行或 ob 包不可 import

**解决**:
```bash
python src/setup_ob.py  # 注册 sections
python -c "from ob import init, track; from ob.api import _NATIVE; print(f'OK _NATIVE={_NATIVE}')"
```

### track 失败进 .errors.json

**可能原因**:
- section_map 缓存过期,需重跑 `setup_ob.py`
- PID 文件冲突,多个 pipeline 同时运行
- ob 包未正确安装(`_NATIVE=False`)

**解决**:
1. 检查 `.errors.json` 内容
2. 重跑 `setup_ob.py` 更新 section_map
3. 确保 pipeline 单线程运行

### `ob status` Authors 数 > 24

**原因**: `author_add` 重复调用(幂等,无害)

**解决**: 忽略,不影响功能

### ob blame / ob show 返回空

**原因**: 未调用 `clean_ob()` 合并 PID 文件

**解决**:
```bash
ob clean -d output/  # 合并后即可查询
```

## HuggingFace 发布

发布包包含三个核心文件:

- `dataset.jsonl` — 成品数据集,所有 QA 的 line_hash 与 .ob/document-index/ 对应
- `README.md` — dataset card,说明数据来源、用途、许可证
- `LICENSE` — 许可证文件

用户可从 HuggingFace Hub 下载 `dataset.jsonl`,用 `ob blame -d output/ output/dataset.jsonl N` 直接查询来源。

## 不集成的事

以下功能不在 teasecorpus 集成范围内:

### DEP-5 export

`ob export-copyright` 可导出版权文件,但不进入 pipeline workflow。

### Embedding reconcile

dump 是静态快照,不需 reconcile(仅适用于持续更新的数据集)。

### Token-level tracking

QA 级 provenance 不需要 tokenizer 级追踪。

### PII 剥离

当前实现保留 `name` + `email` 字段。生产部署可按论文 §6 剥离 PII:

```bash
# 可选:从 .ob/authors/ 移除 name/email,只留 SHA-256 id
```

### Source stack

不使用 `source.append/pop` 模式(thread-local per-file),改用 explicit `track(source=[hashes])` 实现精确的 per-page contributor 粒度。

## 参考文献

- [OriginBlame 论文](https://arxiv.org/abs/2405.06332)
- [RFC 6761 — Reserved Top Level DNS Names](https://www.rfc-editor.org/rfc/rfc6761)
- [RFC 6762 — Multicast DNS](https://www.rfc-editor.org/rfc/rfc6762) (为什么不用 .local)