// Shared state
const App = {
  reader: new OBReader(''),
  dataset: [],   // raw JSONL strings
  parsed: [],    // parsed JSON objects
  hashToLine: new Map(),

  _ready: null,

  // Load dataset from train.jsonl (cached after first call)
  ready() {
    if (this._ready) return this._ready;
    this._ready = (async () => {
      const resp = await fetch('train.jsonl');
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const text = await resp.text();
      const rawLines = text.split('\n').filter(l => l.trim());
      this.dataset = rawLines.map(l => l + '\n');
      this.parsed = this.dataset.map(l => {
        try { return JSON.parse(l); }
        catch (e) { return { messages: [{ role: 'error', content: `Parse error: ${e.message}` }] }; }
      });
    })();
    return this._ready;
  },

  // Build SHA-256 hash → line number index (one-time cost ~10s for 1410 lines)
  async ensureHashIndex() {
    if (this.hashToLine.size > 0) return;
    for (let i = 0; i < this.dataset.length; i++) {
      const hash = await this.reader._sha256(this.dataset[i]);
      this.hashToLine.set(hash, i + 1);
    }
  },

  escapeHtml(text) {
    const d = document.createElement('div');
    d.textContent = text;
    return d.innerHTML;
  },

  detectType(idx) {
    if (idx <= 896) return 'chapter';
    if (idx <= 966) return 'character';  // 896+70
    if (idx <= 1146) return 'episode';   // 966+180
    if (idx <= 1269) return 'music';     // 1146+123
    if (idx <= 1384) return 'volume';    // 1269+115
    if (idx <= 1400) return 'season';    // 1384+16
    return 'movie';
  }
};
