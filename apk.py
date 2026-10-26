#!/usr/bin/env python3
# Copyright (c) 2026 Regis Vidal. MIT License, see LICENSE.
"""A tool to reduce the size of an APK by squeezing the ELF headers and the
manifest, and by signing it without padding. README.md and the article
explain each step.

elf: keeps only the 2 section headers bionic needs.
phdr: drops PT_PHDR and 3 .dynamic entries, puts the section headers over
the program headers, and ends the file after .dynamic.
manifest: UTF-8 strings, empty attribute names, shared strings, line
numbers and comments set to 0, shortest strings first, no closing tags at
the end.
sign: the same v2 signature as apksigner, without the 4 KB alignment.

ELF, binary XML and zip are all little-endian. Offsets in the comments are
in bytes.
"""
import hashlib, struct, subprocess, sys, zipfile

# The v2 signature is built from little-endian integers and length-prefixed
# fields: a 32-bit length, then the bytes. A list is a length-prefixed field
# that holds length-prefixed items.
def u32(n): return struct.pack('<I', n)
def u64(n): return struct.pack('<Q', n)
def lp(b):  return u32(len(b)) + b           # length-prefixed bytes
def seq(*items): return lp(b''.join(lp(i) for i in items))  # list of lp items

# ELF: d[4] is the class, 2 for ELF64 (arm64, x86_64), 1 for ELF32 (armv7).
# The layout is the same, only the field sizes differ. The tuple gives the
# word size, where e_shoff and e_shnum are in the ELF header (e_shstrndx
# follows e_shnum), the size of a section header, and where sh_offset and
# sh_link are in a section header.
def elf_trim(d):
    if d[4] == 2:
        W, shoff_at, num_at, sh, off_at, link_at = '<Q', 0x28, 0x3c, 64, 24, 40
    else:
        W, shoff_at, num_at, sh, off_at, link_at = '<I', 0x20, 0x30, 40, 16, 24
    d = bytearray(d)
    shoff = struct.unpack_from(W, d, shoff_at)[0]
    shnum, shstrndx = struct.unpack_from('<HH', d, num_at)
    assert shoff + sh * shnum == len(d)          # lld writes the headers last
    # Keep the header of .dynamic (sh_type at byte 4 is SHT_DYNAMIC, 6) and
    # the header of the string table it links to, .dynstr.
    hdr = [d[shoff + sh * i:shoff + sh * (i + 1)] for i in range(shnum)]
    dyn = next(h for h in hdr if struct.unpack_from('<I', h, 4)[0] == 6)  # SHT_DYNAMIC
    strtab = hdr[struct.unpack_from('<I', dyn, link_at)[0]]
    struct.pack_into('<I', dyn, link_at, 0)      # the string table is header 0
    for h in (strtab, dyn):
        struct.pack_into('<I', h, 0, 0)          # name: the empty string
    # .shstrtab, the section names, sits right before the headers. Cutting
    # the file at its start removes the names and every header at once.
    out = d[:struct.unpack_from(W, hdr[shstrndx], off_at)[0]]  # cut at .shstrtab
    out += bytes(-len(out) % struct.calcsize(W))  # headers are word aligned
    # The two kept headers go back at the end of the file: point e_shoff at
    # them and set the count. e_shstrndx only has to be nonzero for bionic.
    struct.pack_into(W, out, shoff_at, len(out))
    struct.pack_into('<HH', out, num_at, 2, 1)   # e_shnum 2, e_shstrndx 1
    return out + strtab + dyn

# The same idea for the program headers. The tuple gives the word size,
# where e_phoff and e_phnum are in the ELF header, the size of a program
# header, and where p_offset is in it. p_type is always at byte 0.
def phdr_drop(d):
    if d[4] == 2:
        W, phoff_at, num_at, ph, off_at = '<Q', 0x20, 0x38, 56, 8
    else:
        W, phoff_at, num_at, ph, off_at = '<I', 0x1c, 0x2c, 32, 4
    d = bytearray(d)
    phoff = struct.unpack_from(W, d, phoff_at)[0]
    n = struct.unpack_from('<H', d, num_at)[0]
    t = d[phoff:phoff + ph * n]
    # Only safe when lld's layout is the expected one: PT_PHDR first, then
    # the PT_LOAD that maps the start of the file, ELF header included.
    assert struct.unpack_from('<I', t, 0)[0] == 6         # PT_PHDR
    assert struct.unpack_from('<I', t, ph)[0] == 1        # PT_LOAD
    assert struct.unpack_from(W, t, ph + off_at)[0] == 0  # at offset 0
    # Move the other headers up one place and count one less. Nothing else
    # moves, so no address in the file changes.
    d[phoff:phoff + ph * n] = t[ph:] + bytes(ph)          # zeros compress
    struct.pack_into('<H', d, num_at, n - 1)
    # .dynamic is a list of (tag, value) pairs, each two words. Keep all but
    # DT_SYMENT (11), DT_RELAENT (9) and DT_PLTREL (20), and fill the end
    # with zeros, which also reads as the DT_NULL that ends the list.
    dyn = next(i for i in range(phoff, phoff + ph * (n - 1), ph)
               if struct.unpack_from('<I', d, i)[0] == 2)   # PT_DYNAMIC
    off = struct.unpack_from(W, d, dyn + off_at)[0]
    size = struct.unpack_from(W, d, dyn + 4 * off_at)[0]    # p_filesz
    e = 2 * struct.calcsize(W)
    keep = b''.join(d[i:i + e] for i in range(off, off + size, e)
                    if struct.unpack_from(W, d, i)[0] not in (9, 11, 20))
    d[off:off + size] = keep + bytes(size - len(keep))
    return d

# The 2 section headers go in fields bionic never reads. ELF64: PT_DYNAMIC
# reads as the .dynamic header (p_flags 6 = SHT_DYNAMIC, p_paddr and
# p_memsz become sh_offset and sh_link), the string table header goes in
# the zeros phdr_drop left. ELF32: over p_align of PT_DYNAMIC, the zeros
# and an undefined symbol's st_value/st_size.
def shdr_overlap(d):
    d = bytearray(d)
    if d[4] == 2:
        W, shoff_at, num_at, phoff, ph = '<Q', 0x28, 0x3c, 0x40, 56
        P_OFF, P_PADDR, P_FILESZ, P_MEMSZ, P_ALIGN = 8, 24, 32, 40, 48
        S_TYPE, S_OFF, S_SIZE, S_LINK, sh = 4, 24, 32, 40, 64
    else:
        W, shoff_at, num_at, phoff, ph = '<I', 0x20, 0x30, 0x34, 32
        P_OFF, P_PADDR, P_FILESZ, P_MEMSZ, P_ALIGN = 4, 12, 16, 20, 28
        S_TYPE, S_OFF, S_SIZE, S_LINK, sh = 4, 16, 20, 24, 40
    w = struct.calcsize(W)
    load_rw, dyn = phoff + ph, phoff + 2 * ph        # after phdr_drop
    assert d[load_rw] == 1 and d[dyn] == 2
    dyn_off = struct.unpack_from(W, d, dyn + P_OFF)[0]
    shoff = struct.unpack_from(W, d, shoff_at)[0]    # old header 0: .dynstr
    assert struct.unpack_from('<I', d, shoff + S_TYPE)[0] == 3
    str_off, str_sz = struct.unpack_from('<' + W[1] * 2, d, shoff + S_OFF)
    n = 0                                            # entries up to DT_NULL
    while struct.unpack_from(W, d, dyn_off + 2 * w * n)[0] != 0:
        n += 1
    dyn_sz = 2 * w * (n + 1)
    struct.pack_into(W, d, dyn + P_FILESZ, dyn_sz)
    struct.pack_into(W, d, load_rw + P_FILESZ, dyn_sz)   # the GOT is bss
    if w == 8:
        s0 = dyn                                     # p_flags 6 = SHT_DYNAMIC
        struct.pack_into(W, d, dyn + P_PADDR, dyn_off)
        struct.pack_into(W, d, dyn + P_MEMSZ, 1)     # sh_link 1
    else:
        s0 = dyn + P_ALIGN                           # runs into the zeros
        struct.pack_into('<I', d, s0 + S_TYPE, 6)
        struct.pack_into('<' + W[1] * 3, d, s0 + S_OFF, dyn_off, dyn_sz, 1)
    s1 = s0 + sh
    struct.pack_into('<I', d, s1 + S_TYPE, 3)
    struct.pack_into('<' + W[1] * 2, d, s1 + S_OFF, str_off, str_sz)
    # e_shoff, then e_shnum 2, e_shstrndx 1
    struct.pack_into(W, d, shoff_at, s0)
    struct.pack_into('<HH', d, num_at, 2, 1)
    return d[:dyn_off + dyn_sz]

# Binary XML: an 8 byte header, the string pool chunk, the resource map (the
# resource ids of the first strings, the attribute names), then the nodes.
# Every chunk starts with its type (16 bits), its header size (16 bits) and
# its total size (32 bits).
# A UTF-16 string is [length][text][0] in 16-bit units, a UTF-8 one is
# [length in UTF-16 units][length in bytes][text][0] in bytes.
def small_manifest(x):
    UTF8 = 0x100
    # The string pool header, at byte 8: type, header size, chunk size,
    # number of strings, number of styles, flags, where the strings start.
    # The table of string offsets follows the header.
    _, phs, psize, n, styles, flags, start = struct.unpack_from('<HHIIIII', x, 8)
    assert styles == 0 and not flags & UTF8
    strs = []
    for o in struct.unpack_from('<%dI' % n, x, 8 + phs):
        p = 8 + start + o
        k = struct.unpack_from('<H', x, p)[0]
        strs.append(x[p + 2:p + 2 + 2 * k].decode('utf-16le'))
    t, _, size = struct.unpack_from('<HHI', x, 8 + psize)
    assert t == 0x180                        # the resource map
    # One 32-bit resource id per attribute name. Android matches attributes
    # by these ids, so the names themselves can be empty, except "name".
    # Actions and categories are looked up by it.
    nmap = (size - 8) // 4
    for i in range(nmap):
        if strs[i] != 'name':
            strs[i] = ''
    # The map fixes the first strings, the others can go in any order.
    # Shortest first deflates better.
    order = list(range(nmap)) + sorted(range(nmap, n), key=lambda i: len(strs[i]))
    new = {old: i for i, old in enumerate(order)}
    # The new pool, in UTF-8: both lengths fit in one byte each below 128.
    pool, offs, seen = b'', [], {}
    for i in order:
        b = strs[i].encode()
        assert len(b) < 128                  # one byte lengths
        if b not in seen:                    # equal strings share one entry
            seen[b] = len(pool)
            pool += bytes([len(strs[i]), len(b)]) + b + b'\0'
        offs.append(seen[b])
    pool += bytes(-len(pool) % 4)            # chunks are 4-byte aligned
    start = phs + 4 * n
    chunk = (struct.pack('<HHIIIIII', 1, phs, start + len(pool), n, 0,
                         flags | UTF8, start, 0)
             + struct.pack('<%dI' % n, *offs) + pool)
    # The nodes refer to strings by their index in the pool, and the order
    # changed: every index goes through remap().
    rest = bytearray(x[8 + psize:])
    def remap(p):                            # a string index, -1 for none
        i = struct.unpack_from('<i', rest, p)[0]
        if i >= 0:
            struct.pack_into('<i', rest, p, new[i])
    # A node: the chunk header (8 bytes), the line number at byte 8, a
    # comment at 12, then the namespace and the name of the tag at 16 and
    # 20. A start tag also gives, at 24, where its attributes start (from
    # byte 16), the size of one attribute and their count. An attribute is
    # a namespace, a name, a raw value, then a typed value whose type is at
    # byte 15 and whose data is at 16.
    nodes = []
    p = size                                 # the nodes, after the map
    while p < len(rest):
        t, _, sz = struct.unpack_from('<HHI', rest, p)
        assert t in (0x102, 0x103)           # start and end tags only
        struct.pack_into('<II', rest, p + 8, 0, 0)   # line, comment
        remap(p + 16)                        # namespace
        remap(p + 20)                        # name
        if t == 0x102:                       # a start tag's attributes
            at, asz, count = struct.unpack_from('<HHH', rest, p + 24)
            for a in range(p + 16 + at, p + 16 + at + asz * count, asz):
                remap(a)                     # namespace
                remap(a + 4)                 # name
                remap(a + 8)                 # raw value
                if rest[a + 15] == 3:        # string value
                    remap(a + 16)
        nodes.append((t, p))
        p += sz
    # The closing tags at the end can go: the parser stops at the end of the
    # data.
    while nodes[-1][0] == 0x103:
        rest = rest[:nodes.pop()[1]]
    # The file header keeps its type and header size, with the new total.
    return x[:4] + u32(8 + len(chunk) + len(rest)) + chunk + bytes(rest)

VERSION = '''apk.py 1.0
Copyright (c) 2026 Regis Vidal
MIT License, see LICENSE.'''

USAGE = '''usage: apk.py command files

A tool to reduce the size of an APK by squeezing the ELF headers and the
manifest, and by signing it without padding.

  elf libmain.so            2 section headers instead of 10
  phdr libmain.so           smaller headers, file ends after .dynamic
  manifest file.apk         smaller binary manifest
  sign unsigned.apk key.pem cert.der out.apk
                            v2 signature, no padding
  help                      this text
  version                   version, copyright and license

elf, phdr and manifest rewrite the file in place.'''

NARGS = {'elf': 1, 'phdr': 1, 'manifest': 1, 'sign': 4}
argv = sys.argv[1:]
if argv[:1] in (['help'], ['-h'], ['--help']):
    print(USAGE)
    sys.exit()
if argv[:1] in (['version'], ['--version']):
    print(VERSION)
    sys.exit()
if not argv or argv[0] not in NARGS or len(argv) != 1 + NARGS[argv[0]]:
    sys.exit(USAGE)                           # to stderr, exit status 1
mode, *args = argv
if mode == 'elf':
    (path,) = args
    d = open(path, 'rb').read()
    open(path, 'wb').write(elf_trim(d))
    sys.exit()
if mode == 'phdr':
    (path,) = args
    d = open(path, 'rb').read()
    open(path, 'wb').write(shdr_overlap(phdr_drop(d)))
    sys.exit()
if mode == 'manifest':
    (path,) = args
    with zipfile.ZipFile(path) as z:
        files = [(i, z.read(i)) for i in z.infolist()]
    # Same entries, same order and compression, dated 1980 like aapt2's.
    with zipfile.ZipFile(path, 'w') as z:
        for i, data in files:
            if i.filename == 'AndroidManifest.xml':
                data = small_manifest(data)
            z.writestr(zipfile.ZipInfo(i.filename), data, i.compress_type, 9)
    sys.exit()

src, key, cert, out = args
apk = open(src, 'rb').read()

# Split the zip: the end record is the last 22 bytes (no zip comment), and it
# holds the central directory offset at byte 16.
eocd = apk[-22:]
assert eocd[:4] == b'PK\5\6', 'zip has a comment or is not a zip'
cd_off = struct.unpack('<I', eocd[16:20])[0]
entries, cd = apk[:cd_off], apk[cd_off:-22]

# Digest: each part in 1 MB chunks. A chunk hash covers 0xa5, the length
# and the chunk, the top hash 0x5a, the chunk count and the chunk hashes.
# The end record's offset already points where the block will start.
MB = 1 << 20
chunks = [p[i:i + MB] for p in (entries, cd, eocd)
          for i in range(0, len(p), MB)]
top = hashlib.sha256(b'\x5a' + u32(len(chunks)) + b''.join(
    hashlib.sha256(b'\xa5' + u32(len(c)) + c).digest() for c in chunks)).digest()

# Algorithm id 0x0201: ECDSA with SHA-256, for the digest and the signature.
ECDSA_SHA256 = 0x0201
cert_der = open(cert, 'rb').read()
pubkey = subprocess.run(['openssl', 'pkey', '-in', key, '-pubout', '-outform', 'DER'],
                        capture_output=True, check=True).stdout

# The signed data: the digests, the certificates, and the additional
# attributes. This is what the key signs.
signed_data = (seq(u32(ECDSA_SHA256) + lp(top))   # digests
               + seq(cert_der)                    # certificates
               + lp(b''))                         # additional attributes: none
# nonce-type:1 is RFC 6979: the same key and data give the same signature.
sig = subprocess.run(['openssl', 'dgst', '-sha256', '-sign', key,
                      '-sigopt', 'nonce-type:1'],
                     input=signed_data, capture_output=True, check=True).stdout

# A signer: the signed data, its signatures, and the public key that checks
# them. The v2 value is the list of signers, here one.
signer = lp(signed_data) + seq(u32(ECDSA_SHA256) + lp(sig)) + lp(pubkey)
v2 = lp(lp(signer))                               # list with one signer

# The signing block: its size, ID-value pairs (each with its own 64-bit
# length), the size again, and a magic string. The size counts everything
# after the first size field. apksigner adds a padding pair here.
V2_ID = 0x7109871a
pair = u64(4 + len(v2)) + u32(V2_ID) + v2
size = len(pair) + 8 + 16                         # pairs + size + magic
block = u64(size) + pair + u64(size) + b'APK Sig Block 42'

# The block goes right after the entries, where apksigner puts zeros up to
# the next 4 KB. The central directory moves right by the size of the block,
# and so does its offset in the end record.
eocd = eocd[:16] + u32(cd_off + len(block)) + eocd[20:]
open(out, 'wb').write(entries + block + cd + eocd)
