---
title: teasecorpus provenance explorer
emoji: 🔍
sdk: static
---

# teasecorpus provenance explorer

Static provenance explorer for [teasecorpus](https://huggingface.co/datasets/tzbkk/teasecorpus) — a ChatML SFT dataset with [originblame](https://arxiv.org/abs/2607.13037) record-level contributor provenance.

This Space reads the `.ob/` provenance shard format directly in the browser:

- **Browse**: paginated table (50/page), filter by QA type or search content, click any row for provenance. Jump to any line by number.
- **Author Lookup**: table of all 23 contributors with wiki page counts. Click to see all QA records derived from their edits.

Everything runs client-side. The `.ob/` directory is included as static assets — no server, no build step.

## Files

| File | Purpose |
|------|---------|
| `index.html` | Redirects to browse.html |
| `browse.html` | Paginated browse table with type/search filter, line jump, provenance detail |
| `author.html` | Author table + search by contributor name |
| `style.css` | Shared styles |
| `app.js` | Shared state (dataset loader, utilities) |
| `ob-reader.js` | Pure JS `.ob/` shard reader |
| `train.jsonl` | Full dataset (1410 ChatML records) |
| `.ob/` | Provenance metadata (482 shard files) |
