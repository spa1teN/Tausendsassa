#!/usr/bin/env python3
"""Blank-detector for headless-Chrome screenshots (stdlib only).

Usage: verify_png.py file.png  -> exit 1 if the image is blank/near-blank.
Exists because the model backend may not support vision — this gives a
programmatic "did the page actually render?" signal next to the PNG.
"""
import sys, zlib, struct, collections

def rows(path):
    d = open(path, 'rb').read()
    assert d[:8] == b'\x89PNG\r\n\x1a\n', 'not a PNG'
    pos, idat, w, h, bpp = 8, b'', 0, 0, 4
    while pos < len(d):
        ln, typ = struct.unpack('>I4s', d[pos:pos+8])
        if typ == b'IHDR':
            w, h, depth, ctype = struct.unpack('>IIBB', d[pos+8:pos+18])
            assert depth == 8 and ctype == 6, f'unsupported PNG (depth={depth} ctype={ctype})'
        elif typ == b'IDAT':
            idat += d[pos+8:pos+8+ln]
        pos += 12 + ln
    raw = zlib.decompress(idat)
    stride = w * bpp
    prev = bytearray(stride)
    out = []
    p = 0
    for _ in range(h):
        f = raw[p]; line = bytearray(raw[p+1:p+1+stride]); p += 1 + stride
        for i in range(stride):
            a = line[i-bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i-bpp] if i >= bpp else 0
            if f == 1: line[i] = (line[i] + a) & 255
            elif f == 2: line[i] = (line[i] + b) & 255
            elif f == 3: line[i] = (line[i] + (a+b)//2) & 255
            elif f == 4:
                pp = a+b-c; pa, pb, pc = abs(pp-a), abs(pp-b), abs(pp-c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 255
        out.append(bytes(line)); prev = line
    return w, h, out

w, h, lines = rows(sys.argv[1])
colors = collections.Counter()
for line in lines[::max(1, h//200)]:                      # sample ~200 rows
    for i in range(0, len(line), 4*max(1, w//400)):       # ~400 px per row
        colors[line[i:i+3]] += 1
total = sum(colors.values())
top_share = colors.most_common(1)[0][1] / total
print(f'{w}x{h}, {len(colors)} distinct sampled colors, dominant color share {top_share:.1%}')
if len(colors) < 10 or top_share > 0.98:
    print('LOOKS BLANK'); sys.exit(1)
print('OK: non-blank')
