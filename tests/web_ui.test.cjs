const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../local_encoder/static/index.html'), 'utf8');
const handoff = require('../local_encoder/static/desktop.js');

test('browser handoff preserves a provider URL and rejects credentials, local files and extra commands', () => {
  const params = new URLSearchParams({ site: 'https://example.test/subsite', url: 'https://provider.test/watch?v=a&list=b#t=30' });
  const link = 'avideo-local-encoder://open?' + params;
  assert.deepEqual(handoff.parse(link), { site: 'https://example.test/subsite/', url: params.get('url') });
  assert.deepEqual(handoff.fromFragment('#avideo=' + encodeURIComponent(link)), handoff.parse(link));
  for (const extra of ['&pass=secret', '&site=https://other.test/']) assert.throws(() => handoff.parse(link + extra));
  for (const url of ['file:///private/video.mp4', 'javascript:alert(1)', 'https://user:secret@provider.test/video']) {
    params.set('url', url);
    assert.throws(() => handoff.parse('avideo-local-encoder://open?' + params));
  }
  assert.equal(handoff.fromFragment('#avideo=%invalid').invalid, true);
});

test('an external site is not silently mapped to another saved account or submitted', () => {
  const start = html.indexOf('  function acceptHandoff()');
  const end = html.indexOf('  useEffect(', start);
  const state = { form: null, connection: null, active: 'old', selected: null };
  const context = {
    handoff: { site: 'https://destination.test/', url: 'https://provider.test/watch?v=1' },
    sites: [{ url: 'https://other.test/', username: 'admin', sessionId: 'other-session' }],
    normUrl: url => url,
    connectionGeneration: { current: 0 },
    setConn: value => { state.connection = value; }, setCategories() {},
    setForm: value => { state.form = value; }, setActiveKey: value => { state.active = value; },
    setEditing() {}, setTab() {}, setVideoUrl: value => { state.video = value; },
    selectSite: value => { state.selected = value; }, setHandoff() {},
  };
  vm.createContext(context);
  vm.runInContext(html.slice(start, end) + '\nacceptHandoff();', context);
  assert.equal(state.form.url, 'https://destination.test/');
  assert.equal(state.form.password, '');
  assert.equal(state.connection.state, 'none');
  assert.equal(state.active, '');
  assert.equal(state.selected, null);
  assert.equal(state.video, 'https://provider.test/watch?v=1');
});
const uploadCode = html.slice(html.indexOf('  function sendFile('), html.indexOf('  async function report('));

test('a delayed response from a previous site cannot replace the handoff destination', async () => {
  const start = html.indexOf('  async function selectSite(s)');
  const end = html.indexOf('  async function connect()', start);
  const state = { applied: false, updates: 0 };
  let resolve;
  const context = {
    connectionGeneration: { current: 0 }, siteKey: s => s.url,
    setForm() {}, setActiveKey() {}, setConn() {}, setEditing() {},
    api: () => new Promise(done => { resolve = done; }),
    applyConnection() { state.applied = true; }, updateSite() { state.updates++; },
  };
  vm.createContext(context);
  vm.runInContext(html.slice(start, end), context);
  const pending = context.selectSite({ url: 'https://old.test/', username: 'admin', sessionId: 'old-session' });
  context.connectionGeneration.current++; // accepting a different handoff invalidates this response
  resolve({ ok: true, data: { ok: true } });
  await pending;
  assert.equal(state.applied, false);
  assert.equal(state.updates, 0);
});

function harness(statuses) {
  const original = ['one.mp4', 'two.mp4', 'three.mp4'].map(name => ({ name, size: 10 }));
  const state = { files: [...original], transfers: [], sent: [], expired: false, error: null, title: 'Title', desc: 'Description' };
  const ctx = {
    connected: true, tab: 'files', files: state.files, title: state.title, desc: state.desc,
    submittingRef: { current: false }, setSubmitting: value => { state.submitting = value; },
    currentOptions: () => ({ session_id: 'test', categories_id: 0, description: state.desc, format: 'auto', resolutions: [], use_gpu: true }),
    askNotificationPermission() {},
    setFiles: update => { state.files = typeof update === 'function' ? update(state.files) : update; ctx.files = state.files; },
    setTitle: value => { state.title = value; }, setDesc: value => { state.desc = value; },
    setTransfers: update => { state.transfers = update(state.transfers); },
    setFileError: error => { state.error = error; },
    sessionExpired: () => { state.expired = true; }, showToast() {}, t: key => key,
    FormData: class { append() {} },
    XMLHttpRequest: class {
      constructor() { this.upload = {}; }
      open() {} setRequestHeader() {}
      send() {
        const status = statuses[state.sent.length] ?? 200;
        state.sent.push(status);
        if (status === 'network') { this.onerror(); return; }
        this.status = status;
        this.responseText = JSON.stringify(status < 300 ? { job_id: 'job-' + state.sent.length } : {});
        this.onload();
      }
    },
  };
  vm.createContext(ctx);
  vm.runInContext(uploadCode + '\nglobalThis.submitVideos = submit;', ctx);
  return { state, ctx, original };
}

for (const failure of [500, 401, 'network']) {
  test(`keep failed and unsent files after ${failure}`, async () => {
    const { state, ctx, original } = harness([200, failure]);
    await ctx.submitVideos();
    assert.deepEqual(state.files, original.slice(1));
    assert.equal(state.sent.length, 2);
    assert.equal(state.transfers.length, 0);
    assert.ok(state.error);
    assert.equal(state.title, 'Title');
    assert.equal(state.desc, 'Description');
    assert.equal(state.expired, failure === 401);
    assert.equal(state.submitting, false);
  });
}

test('remove confirmed files and prevent overlapping batch submissions', async () => {
  const { state, ctx } = harness([200, 200, 200]);
  await Promise.all([ctx.submitVideos(), ctx.submitVideos()]);
  assert.equal(state.sent.length, 3);
  assert.equal(state.files.length, 0);
  assert.equal(state.title, '');
  assert.equal(state.desc, '');
  assert.equal(state.submitting, false);
});

test('retry chooses the original account on the same site', () => {
  const start = html.indexOf('function jobAccountMatches(');
  assert.ok(start > 0, 'The page needs a shared account matcher');
  const ctx = {};
  vm.createContext(ctx);
  vm.runInContext(html.slice(start, html.indexOf('const resLabel', start)), ctx);
  const job = { site_url: 'https://avideo.example/', username: 'alice' };
  assert.equal(ctx.jobAccountMatches(job, { url: job.site_url, username: 'bob' }), false);
  assert.equal(ctx.jobAccountMatches(job, { url: 'https://other.example/', username: 'alice' }), false);
  assert.equal(ctx.jobAccountMatches(job, { url: job.site_url, username: 'alice' }), true);
});
