# Dump 管理

## 下载完整 dump

```bash
python src/pipeline_preproc/download_dump.py
```

全量下载 ns0(main) + ns4(project) 命名空间，含完整 revision history。

**选项**:

| 参数 | 说明 |
|------|------|
| `--ns 0 4` | 指定命名空间 |
| `--force` | 强制重下载(覆盖已有 + progress) |
| `--list-only` | 只列出页面标题,不下载 |
| `--delay 2.0` | 请求间隔秒(默认 1.0) |

**断点续传**: `.progress.json` 记录 `last_completed_idx`，中断后重跑自动续。

## 增量更新

```bash
python src/pipeline_preproc/update_dump.py
```

基于 `recentchanges` API，下载上次全量以来的增量修订。

**产物**:

```
wikidump/ns0.delta.20250101-120000.xml      # 增量 XML
wikidump/ns0.deleted.20250101-120000.txt     # 删除/移动清单(有事件时)
```

**限制**:
- 窗口: 30 天(超过 25 天会 warning)
- 不修改原全量 dump 文件
- 合并回全量: 手动或 `download_dump.py --force`

## 数据画像(spike 数据)

| dump | ns | pages | 用途 |
|------|-----|-------|------|
| ns0.xml | 0 (main) | 408 | 章节/角色/剧集/音乐/卷/季度/剧场版 |
| 擅长捉弄的高木同学wiki.xml | 4 (project) | 26 | 译名表 cherry-pick / 社群规则页 |

### ns0.xml 内容分布

```
247 章节 + 14 角色 + 37 剧集 + 41 音乐 + 23 卷 + 3 季度 + 1 剧场版
+ 22 unclassified (画廊/沙盒) = 408 页

Contributors: 23 (21 users + 2 IPs)
铁桶: 2018-2026 (跨所有 page)
Lunisha Kumina: 2024-2026
```

注: `setup_ob.py` 会从 dump 中提取这些 contributor 统计来注册 ob sections。每个 contributor 的 year_range 由其在该 page 的所有 revision timestamps 计算得出。
