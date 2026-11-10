#!/usr/bin/env python3
# oot_amiibo_overlay.py <RomFS.img> <romfs_overlay folder>
# The Legend of Zelda: Ocarina of Time (Switch 2, 0400486024DEC000): amiibo rules, through the game's own Game/AmiiboSetting file. Writes modified copies of it into
# the overlay's amiibo-nolimit/ folder, which the host always layers first (hle_fs.c rom_overlay_set): every AmiiboDropActorSettingSet entry has EnableDailyLimit false (the game's two
# mask entries already do; the drop entries leave it unset, which the game takes as on). variant() can also double the drop chances (x2), unused.
# The game's file decides which amiibo count (decoded with MurmurHash3 against the game's own names): NumberingID_1277 and _1279 (one mask each, no daily limit), SeriesID AmiiboSeriesID09
# (the Legend of Zelda amiibo series) and CharacterBaseID Link, Zelda and Ganon (any series): 3-5 random drops, once a day each.
# The game's files are read from your own dump; nothing of the game is in this repository.
import sys, os, struct, zlib
PATH = 'Game/AmiiboSetting/AmiiboSetting.game__ui__AmiiboSetting.bgyml'
RSTB = 'System/Resource/ResourceSizeTable.Product.111.Nin_Ounce_NVN2.rsizetable.zs'

def rstb_raise(z, factor=2):
    # the resource size table (REST: CRC32 of the path → bytes the game reserves for loading the file) with this file's entry raised: the game's heap for the file
    # comes from it, and a 2,448-byte rewrite of the 1,476-byte file ran it out (a null allocation at main+0xe156e4, crash at 5 s). Returns the new .zs bytes.
    import zstandard
    d = bytearray(zstandard.ZstdDecompressor().decompress(z, max_output_size=1 << 28)); assert d[:4] == b'REST', 'not a resource size table'
    key = struct.pack('<I', zlib.crc32(PATH.encode())); i = d.find(key)
    assert i > 0 and d.find(key, i + 1) == -1, 'the size table has no single entry for ' + PATH
    old = struct.unpack_from('<I', d, i + 4)[0]; assert 1024 < old < 1 << 20, 'implausible size table entry %d' % old
    struct.pack_into('<I', d, i + 4, old * factor)
    return zstandard.ZstdCompressor(level=19).compress(bytes(d)), old, old * factor

# ---- BYML v7 (little endian), the node types this file uses: dict C1, array C0, string A0, bool D0, int D1, float D2, uint D3 ----
class T:   # a typed scalar, so a round trip keeps each value's node type
    __slots__ = ('t', 'v')
    def __init__(s, t, v): s.t, s.v = t, v
    def __eq__(s, o): return isinstance(o, T) and s.t == o.t and s.v == o.v
    def __repr__(s): return 'T(%#x,%r)' % (s.t, s.v)

def parse(b):
    assert b[:2] == b'YB', 'not a little-endian BYML'
    ver, kt, st, root = struct.unpack_from('<HIII', b, 2)
    def strtab(off):
        if not off: return []
        n = struct.unpack_from('<I', b, off)[0] >> 8; offs = struct.unpack_from('<%dI' % (n + 1), b, off + 4)
        return [b[off + o:b.index(b'\0', off + o)].decode() for o in offs[:n]]
    keys, strs = strtab(kt), strtab(st)
    def node(t, v):
        if t == 0xA0: return T(t, strs[v])
        if t in (0xC0, 0xC1): return cont(v)
        if t == 0xD2: return T(t, struct.unpack('<f', struct.pack('<I', v))[0])
        if t == 0xD1: return T(t, struct.unpack('<i', struct.pack('<I', v))[0])
        if t in (0xD0, 0xD3): return T(t, v)
        raise ValueError('node type %#x not handled' % t)
    def cont(off):
        t = b[off]; n = int.from_bytes(b[off + 1:off + 4], 'little')
        if t == 0xC0:
            types = b[off + 4:off + 4 + n]; vo = off + 4 + ((n + 3) & ~3)
            return [node(types[i], struct.unpack_from('<I', b, vo + 4 * i)[0]) for i in range(n)]
        if t == 0xC1:
            d = {}
            for i in range(n):
                e = off + 4 + 8 * i; k = int.from_bytes(b[e:e + 3], 'little'); d[keys[k]] = node(b[e + 3], struct.unpack_from('<I', b, e + 4)[0])
            return d
        raise ValueError('container type %#x not handled' % t)
    return ver, cont(root)

def write(ver, root):
    keys, strs = set(), set()
    def collect(x):
        if isinstance(x, dict):
            for k, v in x.items(): keys.add(k); collect(v)
        elif isinstance(x, list):
            for v in x: collect(v)
        elif x.t == 0xA0: strs.add(x.v)
    collect(root)
    keys = sorted(keys, key=lambda s: s.encode()); strs = sorted(strs, key=lambda s: s.encode())
    ki = {k: i for i, k in enumerate(keys)}; si = {s: i for i, s in enumerate(strs)}
    out = bytearray(16)
    def align():
        while len(out) % 4: out.append(0)
    def strtab(lst):
        if not lst: return 0
        off = len(out); out.extend(struct.pack('<I', 0xC2 | len(lst) << 8)); table = len(out); out.extend(b'\0' * 4 * (len(lst) + 1))
        for i, s in enumerate(lst): struct.pack_into('<I', out, table + 4 * i, len(out) - off); out.extend(s.encode() + b'\0')
        struct.pack_into('<I', out, table + 4 * len(lst), len(out) - off); align(); return off
    kt = strtab(keys); st = strtab(strs)
    def val(x):   # (type, u32): containers are written after their parent (breadth first), so their slot is patched later
        if isinstance(x, (dict, list)): return (0xC1 if isinstance(x, dict) else 0xC0), None
        if x.t == 0xA0: return x.t, si[x.v]
        if x.t == 0xD2: return x.t, struct.unpack('<I', struct.pack('<f', x.v))[0]
        if x.t == 0xD1: return x.t, x.v & 0xffffffff
        return x.t, int(x.v)
    memo = {}
    def canon(x):   # identical containers are written once and shared, as Nintendo's writer does: the game sizes its heap for the file by the resource size table, so a bigger file crashes it
        if isinstance(x, dict): return ('d',) + tuple((k, canon(v)) for k, v in sorted(x.items()))
        if isinstance(x, list): return ('a',) + tuple(canon(v) for v in x)
        return (x.t, x.v)
    def emit(x):   # writes one container, then its child containers; returns its offset
        c = canon(x)
        if c in memo: return memo[c]
        align(); off = len(out); slots = []; memo[c] = off
        if isinstance(x, dict):
            items = sorted(x.items(), key=lambda kv: ki[kv[0]])
            out.extend(struct.pack('<I', 0xC1 | len(items) << 8))
            for k, v in items:
                t, u = val(v); e = len(out); out.extend(struct.pack('<I', ki[k] | t << 24) + struct.pack('<I', u or 0))
                if u is None: slots.append((e + 4, v))
        else:
            out.extend(struct.pack('<I', 0xC0 | len(x) << 8)); tv = [val(v) for v in x]
            out.extend(bytes(t for t, _ in tv)); align()
            for (t, u), v in zip(tv, x):
                e = len(out); out.extend(struct.pack('<I', u or 0))
                if u is None: slots.append((e, v))
        for e, v in slots: struct.pack_into('<I', out, e, emit(v))
        return off
    rt = emit(root)
    out[0:16] = b'YB' + struct.pack('<HIII', ver, kt, st, rt)
    return bytes(out)

def variant(data, nolimit, x2):
    import copy; d = copy.deepcopy(data)
    for e in d['AmiiboDropActorSettingSet']:
        if nolimit: e['EnableDailyLimit'] = T(0xD0, 0)
        dl = e.get('DropActorInfoList')
        if x2 and dl and dl['MaxNumberOfDropChance'].v > 1:
            for k in ('MinNumberOfDropChance', 'MaxNumberOfDropChance'): dl[k] = T(dl[k].t, dl[k].v * 2)
    return d

if __name__ == '__main__':
    img, outdir = sys.argv[1], sys.argv[2]
    sys.path.insert(0, os.environ.get('DMT') or os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'dm', 'tools')); import romfs_image as r
    _, o, n = r.read_index(img)[PATH]
    with open(img, 'rb') as f: f.seek(o); orig = f.read(n)
    ver, data = parse(orig)
    assert write(ver, data) == orig, 'the BYML writer does not rewrite the original byte for byte'
    _, o2, n2 = r.read_index(img)[RSTB]
    with open(img, 'rb') as f: f.seek(o2); rstb, before, after = rstb_raise(f.read(n2))
    for name, nolimit, x2 in (('amiibo-nolimit', 1, 0),):
        v = variant(data, nolimit, x2); b = write(ver, v)
        assert parse(b) == (ver, v), name + ': the written file does not read back'
        p = os.path.join(outdir, name, PATH); os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'wb') as f: f.write(b)
        p = os.path.join(outdir, name, RSTB); os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'wb') as f: f.write(rstb)
        drops = sorted({(e['DropActorInfoList']['MinNumberOfDropChance'].v, e['DropActorInfoList']['MaxNumberOfDropChance'].v) for e in v['AmiiboDropActorSettingSet']})
        assert len(b) <= len(orig) + 64, name + ': %d bytes, the original is %d: the game sizes its heap for the file by the original' % (len(b), len(orig))
        print('%-18s %5d bytes  daily limit %s  drop chances %s  size table %d → %d' % (name, len(b), 'off' if nolimit else 'kept', drops, before, after))
