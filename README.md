# teasecorpus

Generate ChatML SFT dataset with contributor provenance tracking from the [擅长捉弄的高木同学](https://karakai-jouzu-no-takagi-san.fandom.com/zh/) Fandom wiki.

Dataset: [https://huggingface.co/datasets/tzbkk/teasecorpus](https://huggingface.co/datasets/tzbkk/teasecorpus)

## Dependencies

This repository depends on two sibling repositories. Clone them to the same parent directory first:

| Repository | Path | Purpose |
|------------|------|---------|
| [py-wikieditor](../py-wikieditor) | `../py-wikieditor/` | Fandom wiki API client (`fandom_bot` package) |
| [rust-originblame](../rust-originblame) | `../rust-originblame/` | Record-level provenance (`ob` Python package + `ob` CLI) |

## Quick Start

```bash
# 1. Clone sibling repositories to the same parent directory
git clone https://github.com/tzbkk/py-wikieditor ../py-wikieditor
git clone https://github.com/tzbkk/rust-originblame ../rust-originblame

# 2. Create venv (requires Python 3.13 to reuse rust-originblame's precompiled PyO3 .so)
uv venv --python 3.13 --seed .venv
source .venv/bin/activate

# 3. Install dependencies (use aliyun mirror for users in China)
pip install -i https://mirrors.aliyun.com/pypi/simple/ \
    -e ../py-wikieditor openai python-dotenv

# 4. Make the ob package importable (precompiled .so files are in rust-originblame/python/src/)
SITE_PKG=$(.venv/bin/python -c "import site; print(site.getsitepackages()[0])")
OB_SRC=$(.venv/bin/python -c "from pathlib import Path; print(Path('../rust-originblame/python/src').resolve())")
echo "$OB_SRC" > "$SITE_PKG/_ob_native.pth"

# 5. Verify
python -c "from ob import init, track; from ob.api import _NATIVE; print(f'ob OK _NATIVE={_NATIVE}')"
python -c "import fandom_bot, openai, dotenv; print('deps OK')"

# 6. Configure
cp .env.example .env   # Edit and add Fandom + LLM credentials

# 7. Register ob sections (one-time setup)
python src/setup_ob.py

# 8. Download dump
python src/pipeline_preproc/download_dump.py

 # 9. Generate QA
python src/pipeline_qa_gen/chapter_qa.py --max-chapters 5 --reset    # Small batch test
python src/pipeline_qa_gen/chapter_qa.py                     # Full run
# ... Other 6 types
# Output to output/.cache/{type}.jsonl (intermediate artifacts, gitignored)

# 10. Merge
python src/merge_outputs.py
# Output to output/dataset.jsonl (final product, same level as output/.ob, gitignored because it can be regenerated)
```

## Data Flow

```
download_dump.py          Fandom API → wikidump/*.xml
        ↓
wiki_parser.py            XML → Structured items (including contributors + timestamps)
        ↓
setup_ob.py (one-time)    contributors → .ob/authors/ + .ob/sections/
        ↓
pipeline_qa_gen/*.py      LLM / template → output/.cache/{type}.jsonl
        ↓                          ↓
                        ob.track → output/.ob/document-index/
        ↓
merge_outputs.py          output/.cache/*.jsonl → output/dataset.jsonl (byte-level concatenation)
```

## QA Generation

| Type | Script | Count | Method |
|------|--------|-------|--------|
| Chapter | `pipeline_qa_gen/chapter_qa.py` | 247 | LLM |
| Character | `pipeline_qa_gen/character_qa.py` | 14 | LLM |
| Episode | `pipeline_qa_gen/episode_qa.py` | 37 | LLM |
| Music | `pipeline_qa_gen/music_qa.py` | 41 | template |
| Volume | `pipeline_qa_gen/volume_qa.py` | 23 | template |
| Season | `pipeline_qa_gen/season_qa.py` | 3 | LLM |
| Movie | `pipeline_qa_gen/movie_qa.py` | 1 | LLM |

## Provenance

Each QA entry includes record-level provenance, enabling precise tracing to wiki contributors. If a contributor's content needs removal (e.g., due to copyright disputes), `ob revoke` can locate and clean up all their derived QA entries, avoiding full deletion. See [Provenance Documentation](docs/provenance.md) for details.

## More

- [Pipeline Details](docs/pipeline.md)
- [Dump Management](docs/dump-management.md)
- [Provenance Details](docs/provenance.md)