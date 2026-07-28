#!/usr/bin/env python3
"""Rebuild the short orp_objects_03 thumbnail tables in the .custom3 texture archives."""
import binascii, hashlib, io, json, re, struct, sys, zipfile

DB = "orp_objects_03"

def decode_path(enc):
    for key in range(256):
        try:
            s = bytes(b ^ key for b in enc).decode("utf-8")
        except UnicodeDecodeError:
            continue
        if s and all(32 <= ord(c) < 127 for c in s) and s.startswith("!client/"):
            return s
    return None

def parse_container(data):
    recs, off = [], 0
    while off + 30 <= len(data):
        nl = struct.unpack_from("<I", data, off + 26)[0]
        if nl <= 0 or nl > 512:
            break
        hs = 30 + nl
        p = decode_path(data[off + 30:off + hs])
        a, b = struct.unpack_from("<II", data, off + 18)
        assert a == b, (off, a, b)
        recs.append({"off": off, "hdr": hs, "payoff": off + hs, "size": a, "path": p})
        off += hs + a
    assert len(data) - off == 1, "unexpected trailer"
    return recs

def find(recs, suffix):
    for r in recs:
        if r["path"] and r["path"].endswith(suffix):
            return r
    raise KeyError(suffix)

def split_tmb(tmb, lines):
    out, pos = [], 0
    for l in lines:
        if b"affiliate=" in l:
            out.append(None); continue
        if pos + 16 > len(tmb):
            out.append(None); continue
        a, _ = struct.unpack_from("<II", tmb, pos + 8)
        end = pos + 0x10 + (a - 4)
        if end > len(tmb):
            out.append(None); continue
        out.append(tmb[pos:end]); pos = end
    return out, pos

def entries(txt):
    lines = [l for l in txt.split(b"\n")[1:] if l]
    names = [re.match(rb'^"([^"]*)"', l).group(1) for l in lines]
    return lines, names

def rebuild(cur_bin, ref_bin, fmt):
    cur = open(cur_bin, "rb").read()
    ref = open(ref_bin, "rb").read()
    crecs, rrecs = parse_container(cur), parse_container(ref)
    ctxt = find(crecs, f"{DB}/{DB}.txt"); ctmb = find(crecs, f"{DB}/{DB}.{fmt}.tmb")
    rtxt = find(rrecs, f"{DB}/{DB}.txt"); rtmb = find(rrecs, f"{DB}/{DB}.{fmt}.tmb")
    cl, cn = entries(cur[ctxt["payoff"]:ctxt["payoff"] + ctxt["size"]])
    rl, rn = entries(ref[rtxt["payoff"]:rtxt["payoff"] + rtxt["size"]])
    cthumbs, used = split_tmb(cur[ctmb["payoff"]:ctmb["payoff"] + ctmb["size"]], cl)
    rthumbs, rused = split_tmb(ref[rtmb["payoff"]:rtmb["payoff"] + rtmb["size"]], rl)
    assert rused == rtmb["size"], "reference thumbnail table is itself incomplete"
    ref_map = dict(zip(rn, rthumbs))
    ref_line = dict(zip(rn, rl))
    out, reused, restored = [], 0, 0
    for line, name, have in zip(cl, cn, cthumbs):
        if b"affiliate=" in line:
            assert ref_map.get(name) is None, name
            continue
        assert ref_line[name] == line, f"entry mismatch for {name.decode()}"
        rec = ref_map[name]
        assert rec is not None, f"no reference thumbnail for {name.decode()}"
        if have is not None:
            assert have == rec, f"thumbnail mismatch for {name.decode()}"
            reused += 1
        else:
            restored += 1
        out.append(rec)
    new_tmb = b"".join(out)
    patched = bytearray(cur)
    patched[ctmb["payoff"]:ctmb["payoff"] + ctmb["size"]] = new_tmb
    struct.pack_into("<II", patched, ctmb["off"] + 18, len(new_tmb), len(new_tmb))
    return bytes(patched), reused, restored, ctmb["size"], len(new_tmb)

def validate(data, fmt):
    recs = parse_container(data)
    seen = 0
    for r in recs:
        m = r["path"] and re.match(r"!client/texdb/([^/]+)/\1\.(?:%s\.)?tmb$" % fmt, r["path"])
        if not m:
            continue
        db = m.group(1)
        txt = find(recs, f"{db}/{db}.txt"); toc = find(recs, f"{db}/{db}.{fmt}.toc")
        dat = find(recs, f"{db}/{db}.{fmt}.dat")
        lines, _ = entries(data[txt["payoff"]:txt["payoff"] + txt["size"]])
        tocb = data[toc["payoff"]:toc["payoff"] + toc["size"]]
        assert len(tocb) // 4 - 1 == len(lines), f"{db}: toc/txt mismatch"
        assert struct.unpack_from("<I", tocb, 0)[0] == dat["size"], f"{db}: toc header != dat size"
        thumbs, used = split_tmb(data[r["payoff"]:r["payoff"] + r["size"]], lines)
        assert used == r["size"], f"{db}: thumbnail table not fully consumed"
        for l, t in zip(lines, thumbs):
            assert (t is None) == (b"affiliate=" in l), f"{db}: thumbnail/entry desync"
        seen += 1
    assert seen, "no thumbnail tables validated"
    return seen

def cli(argv):
    if len(argv) != 5:
        print("usage: rebuild_texture_thumbnails.py <broken container> <donor container> "
              "<etc|dxt|pvr> <output container>\n\n"
              "Containers are the decompressed .custom3_<fmt> payloads (unzip the joined\n"
              "multipart blob first). The donor must contain the same texture database with\n"
              "a complete thumbnail table; every entry name in the broken container has to be\n"
              "present there with an identical listing line.", file=sys.stderr)
        return 2
    broken, donor, fmt, out = argv[1:]
    data, reused, restored, old, new = rebuild(broken, donor, fmt)
    n = validate(data, fmt)
    open(out, "wb").write(data)
    print(f"{out}: thumbnails {old} -> {new} bytes (kept {reused}, restored {restored}), "
          f"{n} databases validated, container {len(data)} bytes, "
          f"crc32 {binascii.crc32(data) & 0xffffffff:08X}")
    return 0

if __name__ == "__main__":
    sys.exit(cli(sys.argv))
