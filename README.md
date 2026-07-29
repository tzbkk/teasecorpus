# teasecorpus

Generate ChatML SFT dataset with contributor provenance tracking from the [擅长捉弄的高木同学](https://karakai-jouzu-no-takagi-san.fandom.com/zh/) Fandom wiki.

Dataset: [https://huggingface.co/datasets/tzbkk/teasecorpus](https://huggingface.co/datasets/tzbkk/teasecorpus)

## Dependencies

| Package | Source | Purpose |
|---------|--------|---------|
| [originblame](https://pypi.org/project/originblame/) | PyPI | Record-level provenance (`ob` Python package + `ob` CLI) |
| [py-wikieditor](../py-wikieditor) | sibling repo (`../py-wikieditor/`) | Fandom wiki API client (`fandom_bot` package) |

## Quick Start

```bash
# 1. Clone sibling repository to the same parent directory
git clone https://github.com/tzbkk/py-wikieditor ../py-wikieditor

# 2. Create venv (Python 3.12+)
uv venv --python 3.13 --seed .venv
source .venv/bin/activate

# 3. Install dependencies
pip install originblame openai python-dotenv
pip install -e ../py-wikieditor

# 4. Verify
python -c "from ob import init, track; from ob.api import _NATIVE; print(f'ob OK _NATIVE={_NATIVE}')"
python -c "import fandom_bot, openai, dotenv; print('deps OK')"

# 5. Configure
cp .env.example .env   # Edit and add Fandom + LLM credentials

# 6. Register ob sections (one-time setup)
python src/setup_ob.py

# 7. Download dump
python src/pipeline_preproc/download_dump.py

# 8. Generate QA
python src/pipeline_qa_gen/chapter_qa.py --max-chapters 5 --reset    # Small batch test
python src/pipeline_qa_gen/chapter_qa.py                     # Full run
# ... Other 6 types
# Output to output/.cache/{type}.jsonl (intermediate artifacts, gitignored)

# 9. Merge
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