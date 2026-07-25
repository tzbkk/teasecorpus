# teasecorpus

「[擅长捉弄的高木同学](https://karakai-jouzu-no-takagi-san.fandom.com/zh/)」Fandom wiki → ChatML SFT 数据集。

## 快速开始

```bash
# 安装
python3 -m venv venv && source venv/bin/activate
pip install -e ../py-wikieditor
pip install openai python-dotenv

# 配置
cp .env.example .env   # 编辑填入凭据

# 下载 dump
python src/pipeline_preproc/download_dump.py

# 生成 QA(逐个类型)
python src/pipeline_qa_gen/chapter_qa.py --max 5 --reset    # 先测试
python src/pipeline_qa_gen/chapter_qa.py                     # 全量
# ... 其他 6 类

# 合并
python src/merge_outputs.py
```

## 数据流

```
download_dump.py          Fandom API → wikidump/*.xml
        ↓
wiki_parser.py            XML → 结构化 items
        ↓
pipeline_qa_gen/*.py      LLM / template → ChatML QA pairs
        ↓
merge_outputs.py          → output/wiki_sft/all_data.jsonl
```

## QA 生成

| 类型 | 脚本 | 数量 | 方法 |
|------|------|------|------|
| 章节 | `pipeline_qa_gen/chapter_qa.py` | 247 | LLM |
| 角色 | `pipeline_qa_gen/character_qa.py` | 14 | LLM |
| 剧集 | `pipeline_qa_gen/episode_qa.py` | 37 | LLM |
| 音乐 | `pipeline_qa_gen/music_qa.py` | 41 | template |
| 卷 | `pipeline_qa_gen/volume_qa.py` | 23 | template |
| 季度 | `pipeline_qa_gen/season_qa.py` | 3 | LLM |
| 剧场版 | `pipeline_qa_gen/movie_qa.py` | 1 | LLM |

## 更多

- [Pipeline 详解](docs/pipeline.md)
- [Dump 管理](docs/dump-management.md)
