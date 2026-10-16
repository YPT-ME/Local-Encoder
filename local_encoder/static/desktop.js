// Only a validated site address and optional HTTP(S) media URL cross the browser handoff.
(function (root) {
  'use strict';
  function address(value, site) {
    if (typeof value !== 'string' || !value || value.length > 8192 || /[\s\\]/.test(value)) throw new Error('address');
    var parsed = new URL(value);
    if (!/^https?:$/.test(parsed.protocol) || !parsed.hostname || parsed.username || parsed.password) throw new Error('address');
    if (site && (parsed.search || parsed.hash)) throw new Error('site');
    if (site) parsed.pathname = parsed.pathname.replace(/\/+$/, '') + '/';
    return parsed.href;
  }
  function parse(value) {
    if (typeof value !== 'string' || value.length > 24000 || /[\x00-\x1f]/.test(value)) throw new Error('link');
    var parsed = new URL(value);
    if (parsed.protocol !== 'avideo-local-encoder:' || parsed.host !== 'open' || (parsed.pathname && parsed.pathname !== '/') || parsed.hash) throw new Error('link');
    var params = parsed.searchParams;
    params.forEach(function (_, key) { if (!/^(site|url)$/.test(key) || params.getAll(key).length !== 1) throw new Error('parameter'); });
    var result = { site: address(params.get('site'), true) };
    if (params.get('url')) result.url = address(params.get('url'), false);
    return result;
  }
  function fromFragment(fragment) {
    if (!fragment.startsWith('#avideo=')) return null;
    try { return parse(decodeURIComponent(fragment.slice(8))); } catch (_) { return { invalid: true }; }
  }
  root.LocalEncoderHandoff = { parse: parse, address: address, fromFragment: fromFragment };
  if (typeof module !== 'undefined') module.exports = root.LocalEncoderHandoff;
})(typeof window !== 'undefined' ? window : globalThis);
