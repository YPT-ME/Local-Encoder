// Validated site/media and optional public correlation only; no authorization codes in URLs.
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
    try {
      if (fragment.length > 73000) throw new Error('link');
      var params = new URLSearchParams(fragment.slice(1));
      params.forEach(function (_, key) { if (!/^(avideo|state)$/.test(key) || params.getAll(key).length !== 1) throw new Error('parameter'); });
      var result = parse(params.get('avideo'));
      if (params.has('state')) {
        if (!/^[a-f0-9]{32}$/.test(params.get('state') || '')) throw new Error('authorization');
        result.loginState = params.get('state');
      }
      return result;
    } catch (_) { return { invalid: true }; }
  }
  root.LocalEncoderHandoff = { parse: parse, address: address, fromFragment: fromFragment };
  if (typeof module !== 'undefined') module.exports = root.LocalEncoderHandoff;
})(typeof window !== 'undefined' ? window : globalThis);
