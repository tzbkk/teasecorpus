class OBReader {
  constructor(baseUrl = '') {
    this.base = baseUrl;
    this.authors = new Map();
    this.nameToId = new Map();
    this.sections = new Map();
    this.authorSections = new Map();
    this._manifest = null;
    this._ready = false;
  }

  async _fetchManifest() {
    if (this._manifest) return this._manifest;
    const resp = await fetch(`${this.base}.ob/manifest.txt`);
    this._manifest = (await resp.text()).trim().split('\n');
    return this._manifest;
  }

  async _filesIn(dir) {
    const manifest = await this._fetchManifest();
    const prefix = dir + '/';
    return manifest.filter(f => f.startsWith(prefix)).map(f => f.slice(prefix.length));
  }

  async _readShard(path) {
    const resp = await fetch(`${this.base}${path}`);
    if (!resp.ok) return [];
    const text = await resp.text();
    return text.split('\n').filter(l => l.trim()).map(l => JSON.parse(l));
  }

  async init() {
    const [authorFiles, sectionFiles] = await Promise.all([
      this._filesIn('.ob/authors'),
      this._filesIn('.ob/sections'),
    ]);

    const [authorRecords, sectionRecords] = await Promise.all([
      Promise.all(authorFiles.map(f => this._readShard(`.ob/authors/${f}`))).then(a => a.flat()),
      Promise.all(sectionFiles.map(f => this._readShard(`.ob/sections/${f}`))).then(a => a.flat()),
    ]);

    for (const r of authorRecords) {
      this.authors.set(r.id, r);
      this.nameToId.set(r.name, r.id);
    }
    for (const r of sectionRecords) {
      const sh = r.section_hash;
      this.sections.set(sh, r);
      for (const aid of r.authors) {
        if (!this.authorSections.has(aid)) this.authorSections.set(aid, new Set());
        this.authorSections.get(aid).add(sh);
      }
    }
    this._ready = true;
  }

  async _sha256(text) {
    const buf = new TextEncoder().encode(text);
    const hash = await crypto.subtle.digest('SHA-256', buf);
    return [...new Uint8Array(hash)].map(b => b.toString(16).padStart(2, '0')).join('');
  }

  async blame(lineContent) {
    if (!this._ready) await this.init();
    const hash = await this._sha256(lineContent);
    const shard = hash.substring(0, 2);
    const records = await this._readShard(`.ob/document-index/${shard}`);
    const match = records.find(r => r.line_hash === hash);
    if (!match) return null;
    const sources = (match.sources || []).map(sh => {
      const sec = this.sections.get(sh);
      return {
        hash: sh,
        path: sec?.path || sh,
        authors: (sec?.authors || []).map(aid => {
          const a = this.authors.get(aid);
          return a ? { id: aid, name: a.name } : { id: aid, name: aid };
        }),
        license: sec?.license || '',
        year: sec?.year || '',
      };
    });
    return { lineHash: hash, sources };
  }

  async showByAuthor(name) {
    if (!this._ready) await this.init();
    const aid = this.nameToId.get(name);
    if (!aid) return [];
    const sectionHashes = this.authorSections.get(aid) || new Set();
    if (sectionHashes.size === 0) return [];

    const docFiles = await this._filesIn('.ob/document-index');
    const allRecords = (await Promise.all(
      docFiles.map(f => this._readShard(`.ob/document-index/${f}`))
    )).flat();

    const results = [];
    const seen = new Set();
    for (const r of allRecords) {
      const intersection = (r.sources || []).filter(sh => sectionHashes.has(sh));
      if (intersection.length > 0 && !seen.has(r.line_hash)) {
        seen.add(r.line_hash);
        results.push({ lineHash: r.line_hash, sources: intersection });
      }
    }
    return results;
  }

  sectionDetail(hash) {
    return this.sections.get(hash) || null;
  }
}

if (typeof module !== 'undefined') module.exports = OBReader;
