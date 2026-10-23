#!/usr/bin/env python3
"""HavanaRP launcher update channel (v137, v138: launcher.json notes follow release edits, v140: delta patches).

The launcher (every build, also v136 and older) reads api/runtime/config.json -> "apk".
When apk.version > the installed versionCode it opens the update screen and the install
button downloads apk.manual_update_url (havana.Up) and opens the Android installer.

This script makes the newest GitHub release the single source of truth:
  * newest published, non-prerelease release whose tag is v<number> and that has the asset HavanaRp.apk
  * downloads the asset, reads versionCode / versionName from its AndroidManifest.xml (never trusts the tag),
  * only if versionCode > current config apk.version: rewrites config.json apk{...} and writes
    api/runtime/launcher.json (used by the forum download page as a fallback).
  * v140: release assets named HavanaRp-<from>-<to>.patch (format HVP1, to == the APK versionCode) become
    config.json apk.patches {"<from>": {url, size, sha256, sha256_base, size_base, sha256_out, size_out, to}}
    (read by the v140+ launcher HvDelta; older launchers ignore the key). Every entry is verified before it is
    written: patch header out sha256/size == this APK, base size/sha256 == the HavanaRp.apk of release v<from>.
    Patches for an older target are dropped. No patch assets -> no "patches" key.
Never lowers the version, never touches anything else in config.json (existing apk fields are kept).
Exit 0 = nothing to do or done, 1 = refused (prints why).
"""
import json, os, re, sys, struct, zipfile, hashlib, urllib.request, tempfile

REPO = os.environ.get('GITHUB_REPOSITORY', 'manustest534h-dev/havanarp-cdn')
TOKEN = os.environ.get('GH_TOKEN', '')
ASSET = 'HavanaRp.apk'
CFG = 'api/runtime/config.json'
LJ = 'api/runtime/launcher.json'
PKG = 'com.havanarp.launcher'

def api(url):
    rq = urllib.request.Request(url, headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'havanarp-sync'})
    if TOKEN: rq.add_header('Authorization', 'Bearer ' + TOKEN)
    return json.load(urllib.request.urlopen(rq, timeout=60))

def axml_version(man):
    """versionCode, versionName, package from a binary AndroidManifest.xml"""
    b = man; p = 8
    sp_t, sp_h, sp_sz = struct.unpack('<HHI', b[p:p + 8]); assert sp_t == 1
    cnt, scnt, flags, sstart, ststart = struct.unpack('<IIIII', b[p + 8:p + 28])
    utf8 = bool(flags & 0x100); offs = struct.unpack('<%dI' % cnt, b[p + 28:p + 28 + 4 * cnt])
    def s(i):
        o = p + sstart + offs[i]
        if utf8:
            o += 2 if b[o] & 0x80 else 1
            n = b[o]
            if n & 0x80: n = ((n & 0x7f) << 8) | b[o + 1]; o += 2
            else: o += 1
            return b[o:o + n].decode('utf-8', 'replace')
        n = struct.unpack('<H', b[o:o + 2])[0]
        return b[o + 2:o + 2 + 2 * n].decode('utf-16le', 'replace')
    q = p + sp_sz; rt, rh, rsz = struct.unpack('<HHI', b[q:q + 8]); assert rt == 0x180
    rids = struct.unpack('<%dI' % ((rsz - 8) // 4), b[q + 8:q + rsz])
    q += rsz
    while q < len(b):
        t, h, sz = struct.unpack('<HHI', b[q:q + 8])
        if t == 0x102 and s(struct.unpack('<I', b[q + 20:q + 24])[0]) == 'manifest':
            astart, asize, acount = struct.unpack('<HHH', b[q + 24:q + 30]); vc = vn = pk = None
            for k in range(acount):
                a = q + 16 + astart + k * asize
                ns, an, raw, vsz, r0, typ, data = struct.unpack('<IIIHBBI', b[a:a + 20])
                rid = rids[an] if an < len(rids) else 0
                name = s(an)
                if rid == 0x0101021b: vc = data
                elif rid == 0x0101021c: vn = s(data) if typ == 3 else str(data)
                elif name == 'package': pk = s(raw)
            return vc, vn, pk
        q += sz
    raise ValueError('no manifest element')

PATCH_RE = re.compile(r'HavanaRp-(\d+)-(\d+)\.patch')

def fetch(url, tmp=None):
    """download url -> (sha256 hex, size, bytes or None); big files stream to tmp"""
    rq = urllib.request.Request(url, headers={'User-Agent': 'havanarp-sync'})
    h = hashlib.sha256(); n = 0; buf = bytearray() if tmp is None else None
    with urllib.request.urlopen(rq, timeout=600) as u:
        f = open(tmp, 'wb') if tmp else None
        while True:
            d = u.read(1 << 20)
            if not d: break
            h.update(d); n += len(d)
            if f: f.write(d)
            else: buf += d
        if f: f.close()
    return h.hexdigest(), n, (bytes(buf) if buf is not None else None)

def patch_head(p):
    if p[:4] != b'HVP1' or struct.unpack('>I', p[4:8])[0] != 1: return None
    return {'sha256_base': p[8:40].hex(), 'size_base': struct.unpack('>Q', p[40:48])[0],
            'sha256_out': p[48:80].hex(), 'size_out': struct.unpack('>Q', p[80:88])[0]}

def build_patches(rel, vc, sha, size, releases=None, get=fetch):
    """verified apk.patches dict for release rel (APK versionCode vc, sha256 sha, size size)"""
    out = {}
    if releases is None: releases = api('https://api.github.com/repos/%s/releases?per_page=30' % REPO)
    for a in rel.get('assets', []):
        m = PATCH_RE.fullmatch(a.get('name', ''))
        if not m or a.get('state') != 'uploaded': continue
        frm, to = int(m.group(1)), int(m.group(2))
        if to != vc or frm >= vc: print('patch', a['name'], 'skipped: not for', vc); continue
        psha, pn, pb = get(a['browser_download_url'])
        h = patch_head(pb or b'')
        if pn != a['size'] or not h: print('patch', a['name'], 'REFUSED: size/header'); continue
        if h['sha256_out'] != sha or h['size_out'] != size: print('patch', a['name'], 'REFUSED: output is not this APK'); continue
        base = None
        for r in releases:
            if r.get('draft') or r.get('tag_name') != 'v%d' % frm: continue
            base = next((x for x in r.get('assets', []) if x['name'] == ASSET and x.get('state') == 'uploaded'), None)
        if not base or base['size'] != h['size_base']: print('patch', a['name'], 'REFUSED: no release v%d / base size' % frm); continue
        fd, tmp = tempfile.mkstemp(suffix='.apk'); os.close(fd)
        try: bsha, bn, _ = get(base['browser_download_url'], tmp)
        finally:
            try: os.remove(tmp)
            except OSError: pass
        if bsha != h['sha256_base'] or bn != h['size_base']: print('patch', a['name'], 'REFUSED: base sha256 != release v%d' % frm); continue
        out[str(frm)] = {'url': a['browser_download_url'], 'size': pn, 'sha256': psha, 'sha256_base': h['sha256_base'],
                         'size_base': h['size_base'], 'sha256_out': h['sha256_out'], 'size_out': h['size_out'], 'to': vc}
        print('patch', a['name'], 'OK', pn, 'bytes', psha)
    return dict(sorted(out.items(), key=lambda kv: -int(kv[0])))

def set_patches(apk, patches):
    """True when apk.patches changed"""
    old = apk.get('patches')
    if patches: apk['patches'] = patches
    else: apk.pop('patches', None)
    return old != apk.get('patches')

def pick():
    for r in api('https://api.github.com/repos/%s/releases?per_page=30' % REPO):
        if r.get('draft') or r.get('prerelease'): continue
        if not re.fullmatch(r'v\d+', r.get('tag_name', '')): continue
        a = [x for x in r.get('assets', []) if x['name'] == ASSET and x.get('state') == 'uploaded']
        if a: return r, a[0]
    return None, None

def main():
    rel, asset = pick()
    if not rel: print('no launcher release with', ASSET); return 0
    cfg = json.load(open(CFG, encoding='utf-8'))
    cur = int(cfg.get('apk', {}).get('version') or 0)
    print('newest release', rel['tag_name'], asset['size'], 'config apk.version', cur)
    fd, tmp = tempfile.mkstemp(suffix='.apk'); os.close(fd)
    rq = urllib.request.Request(asset['browser_download_url'], headers={'User-Agent': 'havanarp-sync'})
    h = hashlib.sha256(); n = 0
    with urllib.request.urlopen(rq, timeout=600) as u, open(tmp, 'wb') as f:
        while True:
            d = u.read(1 << 20)
            if not d: break
            f.write(d); h.update(d); n += len(d)
    if n != asset['size']: print('REFUSED: size', n, '!=', asset['size']); return 1
    sha = h.hexdigest()
    m = re.search(r'SHA-256[^0-9a-fA-F]*([0-9a-fA-F]{64})', rel.get('body') or '')
    if m and m.group(1).lower() != sha: print('REFUSED: sha256 in release notes', m.group(1), '!= file', sha); return 1
    vc, vn, pk = axml_version(zipfile.ZipFile(tmp).read('AndroidManifest.xml')); os.remove(tmp)
    print('apk versionCode', vc, 'versionName', vn, 'package', pk, 'sha256', sha)
    if pk != PKG: print('REFUSED: package', pk); return 1
    if vc and vc == cur:
        # v140: same build -> make apk.patches match the release's verified patch assets (patches may be added later)
        apk = cfg.setdefault('apk', {})
        if set_patches(apk, build_patches(rel, vc, sha, n)):
            json.dump(cfg, open(CFG, 'w', encoding='utf-8'), ensure_ascii=False, indent=2); open(CFG, 'a').write('\n')
            print('config.json apk.patches ->', sorted(apk.get('patches', {})))
        # v138: same build already in config.json -> only keep launcher.json (forum page + the launcher update screen line)
        # in step with the release text, so editing the release notes on GitHub is enough.
        try: lj = json.load(open(LJ, encoding='utf-8'))
        except Exception: lj = {}
        if lj.get('versionCode') == vc and (lj.get('notes') != (rel.get('body') or '') or lj.get('name') != (rel.get('name') or rel['tag_name'])):
            lj['notes'] = rel.get('body') or ''; lj['name'] = rel.get('name') or rel['tag_name']
            json.dump(lj, open(LJ, 'w', encoding='utf-8'), ensure_ascii=False, indent=2); open(LJ, 'a').write('\n')
            print('launcher.json notes/name refreshed for', vc); return 0
    if not vc or vc <= cur: print('nothing to do: apk versionCode', vc, '<= config', cur); return 0
    url = asset['browser_download_url']
    apk = cfg.setdefault('apk', {})
    apk.update({'version': vc, 'str': vn or apk.get('str', ''), 'path': url, 'auto_update': True,
                'manual_update': True, 'manual_update_url': url, 'url': url})
    set_patches(apk, build_patches(rel, vc, sha, n))
    json.dump(cfg, open(CFG, 'w', encoding='utf-8'), ensure_ascii=False, indent=2); open(CFG, 'a').write('\n')
    lj = {'version': vn, 'versionCode': vc, 'tag': rel['tag_name'], 'name': rel.get('name') or rel['tag_name'],
          'published_at': rel.get('published_at'), 'size': n, 'sha256': sha, 'url': url,
          'release_url': rel.get('html_url'), 'notes': rel.get('body') or ''}
    json.dump(lj, open(LJ, 'w', encoding='utf-8'), ensure_ascii=False, indent=2); open(LJ, 'a').write('\n')
    print('config.json apk ->', vc, vn, url, 'patches', sorted(apk.get('patches', {})))
    return 0

if __name__ == '__main__':
    sys.exit(main())
