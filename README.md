# teasecorpus

从「[擅长捉弄的高木同学](https://karakai-jouzu-no-takagi-san.fandom.com/zh/)」Fandom wiki 生成带 contributor 溯源的 ChatML SFT 数据集。

## 依赖

本仓库依赖两个 sibling 仓库,需先克隆到同级目录:

| 仓库 | 路径 | 用途 |
|------|------|------|
| [py-wikieditor](../py-wikieditor) | `../py-wikieditor/` | Fandom wiki API 客户端(`fandom_bot` 包) |
| [rust-originblame](../rust-originblame) | `../rust-originblame/` | Record-level provenance(`ob` Python 包 + `ob` CLI) |

## 快速开始

```bash
# 1. 克隆 sibling 仓库到同级目录
git clone https://github.com/tzbkk/py-wikieditor ../py-wikieditor
git clone https://github.com/tzbkk/rust-originblame ../rust-originblame

# 2. 创建 venv(必须 Python 3.13,复用 rust-originblame 预编译的 PyO3 .so)
uv venv --python 3.13 --seed .venv
source .venv/bin/activate

# 3. 装依赖(国内网络用 aliyun mirror)
pip install -i https://mirrors.aliyun.com/pypi/simple/ \
    -e ../py-wikieditor openai python-dotenv

# 4. 让 ob 包可 import(预编译 .so 在 rust-originblame/python/src/)
SITE_PKG=$(.venv/bin/python -c "import site; print(site.getsitepackages()[0])")
OB_SRC=$(.venv/bin/python -c "from pathlib import Path; print(Path('../rust-originblame/python/src').resolve())")
echo "$OB_SRC" > "$SITE_PKG/_ob_native.pth"

# 5. 验证
python -c "from ob import init, track; from ob.api import _NATIVE; print(f'ob OK _NATIVE={_NATIVE}')"
python -c "import fandom_bot, openai, dotenv; print('deps OK')"

# 6. 配置
cp .env.example .env   # 编辑填入 Fandom + LLM 凭据

# 7. 注册 ob sections(一次性)
python src/setup_ob.py

# 8. 下载 dump
python src/pipeline_preproc/download_dump.py

 # 9. 生成 QA
python src/pipeline_qa_gen/chapter_qa.py --max-chapters 5 --reset    # 小批量测试
python src/pipeline_qa_gen/chapter_qa.py                     # 全量
# ... 其他 6 类
# 输出到 output/.cache/{type}.jsonl (中间产物,gitignored)

# 10. 合并
python src/merge_outputs.py
# 输出到 output/dataset.jsonl (成品,与 output/.ob 同级,gitignored 因为可重生成)
```

## 数据流

```
download_dump.py          Fandom API → wikidump/*.xml
        ↓
wiki_parser.py            XML → 结构化 items(含 contributors + timestamps)
        ↓
setup_ob.py (一次性)      contributors → .ob/authors/ + .ob/sections/
        ↓
pipeline_qa_gen/*.py      LLM / template → output/.cache/{type}.jsonl
        ↓                          ↓
                        ob.track → output/.ob/document-index/
        ↓
merge_outputs.py          output/.cache/*.jsonl → output/dataset.jsonl (字节级拼接)
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

## 溯源

每条 QA 附带 record-level provenance,可精确追踪到 wiki 贡献者。若某 contributor 内容需移除（如版权争议），`ob revoke` 可定位并清理其所有衍生 QA，避免全量删除。详见 [溯源文档](docs/provenance.md)。

## 更多

- [Pipeline 详解](docs/pipeline.md)
- [Dump 管理](docs/dump-management.md)
- [Provenance 详解](docs/provenance.md)
