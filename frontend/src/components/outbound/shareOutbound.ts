type Outbound = Record<string, any>;
const decode64 = (s: string) => new TextDecoder().decode(Uint8Array.from(atob(s.replace(/-/g, '+').replace(/_/g, '/').padEnd(Math.ceil(s.length / 4) * 4, '=')), c => c.charCodeAt(0)));
const unbracket = (s: string) => s.replace(/^\[|\]$/g, '');
export function parseShareOutbound(input: string): { outbound: Outbound; warnings: string[] } {
  const match = input.trim().match(/^([a-z0-9]+):\/\/(.*)$/i);
  if (!match) throw new Error('invalid');
  let scheme = match[1].toLowerCase(), body = match[2];
  const warnings: string[] = [];
  let data: any = {};
  if (scheme === 'vmess') {
    data = JSON.parse(decode64(body));
    if (!data.add || !data.port || !data.id) throw new Error('invalid');
    const supported = new Set(['v', 'ps', 'add', 'port', 'id', 'aid', 'scy', 'net', 'type', 'host', 'path', 'tls', 'sni', 'alpn', 'fp']);
    for (const [key, value] of Object.entries(data)) {
      if (!supported.has(key) && value !== '' && value != null) warnings.push(key);
    }
    const params = new URLSearchParams();
    for (const [from, to] of Object.entries({ net: 'type', tls: 'security', sni: 'sni', fp: 'fp', alpn: 'alpn', host: 'host', path: 'path', type: 'headerType' })) if (data[from]) params.set(to, String(data[from]));
    body = `${encodeURIComponent(data.id)}@${String(data.add).includes(':') ? `[${unbracket(String(data.add))}]` : data.add}:${data.port}?${params}#${encodeURIComponent(data.ps || '')}`;
  }
  if (scheme === 'ss' && !body.split(/[?#]/)[0].includes('@')) {
    const cut = body.search(/[?#]/); const suffix = cut < 0 ? '' : body.slice(cut); const encoded = cut < 0 ? body : body.slice(0, cut);
    body = decode64(encoded) + suffix;
  }
  const url = new URL(`${scheme}://${body}`);
  const q = url.searchParams;
  const known = new Set(['type','security','sni','fp','alpn','pbk','sid','spx','pqv','host','path','serviceName','authority','mode','headerType','flow','encryption','mtu','tti','publickey','publicKey','privatekey','privateKey','address','allowedips','allowedIPs','presharedkey','preSharedKey','keepalive','keepAlive','reserved', 'ech', 'vcn', 'pcs', 'cs', 'pinSHA256']);
  q.forEach((_v, k) => { if (!known.has(k) && !warnings.includes(k)) warnings.push(k); });
  const address = unbracket(url.hostname), port = url.port ? Number(url.port) : 443;
  if (!address || !Number.isInteger(port) || port < 1 || port > 65535) throw new Error('invalid');
  let credential = decodeURIComponent(url.username); const password = decodeURIComponent(url.password);
  const tag = decodeURIComponent(url.hash.slice(1));
  let protocol = scheme; let settings: Outbound;
  if (scheme === 'vless') { if (!credential) throw new Error('invalid'); settings = { address, port, id: credential, flow: q.get('flow') || '', encryption: q.get('encryption') || 'none' }; }
  else if (scheme === 'vmess') settings = { vnext: [{ address, port, users: [{ id: data.id, security: data.scy || 'auto' }] }] };
  else if (scheme === 'trojan') { if (!credential) throw new Error('invalid'); settings = { servers: [{ address, port, password: credential }] }; }
  else if (scheme === 'ss') {
    if (!password && !credential.includes(':')) credential = decode64(credential);
    const colon = credential.indexOf(':'); const method = colon >= 0 ? credential.slice(0, colon) : credential; const secret = colon >= 0 ? credential.slice(colon + 1) : password;
    if (!method || !secret) throw new Error('invalid'); protocol = 'shadowsocks'; settings = { servers: [{ address, port, method, password: secret }] };
  } else if (scheme === 'hysteria2' || scheme === 'hy2') { if (!credential) throw new Error('invalid'); protocol = 'hysteria'; settings = { address, port, version: 2 }; }
  else if (scheme === 'wireguard' || scheme === 'wg') {
    protocol = 'wireguard'; const pub = q.get('publicKey') || q.get('publickey'); if (!credential || !pub) throw new Error('invalid');
    const peer: Outbound = { publicKey: pub, endpoint: `${address.includes(':') ? `[${address}]` : address}:${port}`, allowedIPs: (q.get('allowedIPs') || q.get('allowedips') || '0.0.0.0/0,::/0').split(',') };
    const psk = q.get('preSharedKey') || q.get('presharedkey'); if (psk) peer.preSharedKey = psk;
    const keep = q.get('keepAlive') || q.get('keepalive'); if (keep) peer.keepAlive = Number(keep);
    settings = { secretKey: credential, address: (q.get('address') || '').split(',').filter(Boolean), peers: [peer] };
    if (q.get('mtu')) settings.mtu = Number(q.get('mtu')); if (q.get('reserved')) settings.reserved = q.get('reserved')!.split(',').map(Number);
    return { outbound: { tag, protocol, settings }, warnings };
  } else throw new Error('invalid');
  const network = protocol === 'hysteria' ? 'hysteria' : q.get('type') || 'tcp';
  const security = protocol === 'hysteria' ? 'tls' : q.get('security') || (scheme === 'trojan' ? 'tls' : 'none');
  const stream: Outbound = { network, security };
  const transport: Outbound = {};
  const used = new Set<string>();
  const take = (key: string, target = key) => {
    if (q.has(key)) { transport[target] = q.get(key); used.add(key); }
  };
  if (network === 'tcp' && q.get('headerType') === 'http') {
    used.add('headerType');
    const request: Outbound = {};
    if (q.has('path')) { request.path = [q.get('path')]; used.add('path'); }
    if (q.has('host')) { request.headers = { Host: [q.get('host')] }; used.add('host'); }
    transport.header = { type: 'http', request };
  } else if (network === 'tcp' && q.get('headerType') === 'none') used.add('headerType');
  if (['ws', 'httpupgrade', 'xhttp'].includes(network)) { take('host'); take('path'); }
  if (network === 'xhttp') take('mode');
  if (network === 'grpc') {
    take('serviceName');
    if (scheme === 'vmess' && q.has('path') && !q.has('serviceName')) take('path', 'serviceName');
    take('authority');
    if (q.get('mode') === 'multi') { transport.multiMode = true; used.add('mode'); }
    else if (q.get('mode') === 'gun' || q.get('mode') === 'single') used.add('mode');
  }
  if (network === 'kcp') {
    for (const key of ['mtu', 'tti']) {
      if (q.has(key) && Number.isFinite(Number(q.get(key)))) {
        transport[key] = Number(q.get(key)); used.add(key);
      }
    }
  }
  for (const key of ['host', 'path', 'serviceName', 'authority', 'mode', 'headerType', 'mtu', 'tti']) {
    if (q.has(key) && !used.has(key) && !warnings.includes(key)) warnings.push(key);
  }
  if (Object.keys(transport).length) stream[`${network}Settings`] = transport;
  if (security !== 'tls' && security !== 'reality') {
    for (const key of ['sni', 'fp', 'alpn', 'pbk', 'sid', 'spx', 'pqv', 'ech', 'vcn', 'pcs', 'cs', 'pinSHA256']) {
      if (q.has(key) && !warnings.includes(key)) warnings.push(key);
    }
  } else if (security === 'tls') {
    for (const key of ['pbk', 'sid', 'spx', 'pqv']) {
      if (q.has(key) && !warnings.includes(key)) warnings.push(key);
    }
  } else {
    for (const key of ['ech', 'vcn', 'pcs', 'cs', 'pinSHA256']) {
      if (q.has(key) && !warnings.includes(key)) warnings.push(key);
    }
  }
  if (protocol === 'hysteria') stream.hysteriaSettings = { version: 2, auth: credential };
  if (security === 'tls' || security === 'reality') {
    const sec: Outbound = {};
    for (const [from, to] of Object.entries({ sni:'serverName', fp:'fingerprint', pbk:'publicKey', sid:'shortId', spx:'spiderX', pqv:'mldsa65Verify' })) if (q.has(from) && (security === 'reality' || !['pbk', 'sid', 'spx', 'pqv'].includes(from))) sec[to] = q.get(from);
    if (security === 'tls') {
      for (const [from, to] of Object.entries({ ech: 'echConfigList', vcn: 'verifyPeerCertByName', pcs: 'pinnedPeerCertSha256', cs: 'cipherSuites' })) {
        if (q.has(from)) sec[to] = q.get(from);
      }
      if (protocol === 'hysteria' && q.has('pinSHA256')) sec.pinnedPeerCertSha256 = q.get('pinSHA256');
      else if (q.has('pinSHA256')) warnings.push('pinSHA256');
    }
    if (q.has('alpn')) sec.alpn = q.get('alpn')!.split(','); else if (protocol === 'hysteria') sec.alpn = ['h3'];
    stream[`${security}Settings`] = sec;
  }
  return { outbound: { tag, protocol, settings, streamSettings: stream }, warnings };
}
