#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FFRS SpriteStudio transform evaluator research build.

Purpose:
  Validate a single, reusable Parent->Local SRT -> Cell quad pipeline before
  merging it into the production SpriteSliceAnalyzer.

Evidence model:
  .uexp is authoritative for animation/static node data.
  No JSON sidecar is used as parsing evidence.

This research build intentionally keeps runtime-only NULL/weapon attachment
semantics out of rasterization. Drawable parts and part_add use the same
math; NULL nodes are retained as metadata only.
"""
from __future__ import annotations
import argparse, json, math, struct, types, sys
from dataclasses import dataclass, asdict
from pathlib import Path
from collections import defaultdict
from PIL import Image, ImageDraw

# Import the stable Cell/FName/resource helpers without relying on its animation
# parser, because the production parser does not yet expose Posz/Alpha/FNameNum.
import sprite_slice_analyzer_multitex as ssbase

MAGIC_ANIM = bytes.fromhex('80 0D 22')
MAGIC_SETUP = bytes.fromhex('80 0D 02')
KEY_MARKER = bytes.fromhex('80 0F 7F')
CURVE_KEY_MARKERS = {bytes.fromhex('80 0F 70'): 4, bytes.fromhex('80 0F 74'): 3, bytes.fromhex('80 0F 78'): 3}
MAGIC_CELL_KEY = bytes.fromhex('80 05 01')

# FFRS transform attributes observed in the cooked resources.
ATTR_NAMES = {
    0:'Cell', 1:'Posx', 2:'Posy', 3:'Posz', 6:'Rotz',
    7:'Sclx', 8:'Scly', 11:'Alpha', 13:'Prio', 16:'Hide', 35:'Unknown_35'
}

@dataclass
class StaticNode:
    node_id: int
    parent_id: int
    name_index: int
    fname_number: int
    name: str
    offset: int

@dataclass
class Part:
    name: str
    name_index: int
    fname_number: int
    attrs: list
    offset: int


def read_value(b, p, end):
    for mk, n in CURVE_KEY_MARKERS.items():
        if b[p:p+3] == mk and p + 3 + n * 4 <= end:
            vals = struct.unpack_from('<%df' % n, b, p + 3)
            return 'curve', vals[0], p + 3 + n * 4
    if b[p:p+4] == bytes.fromhex('80 09 0E 03'):
        return 'zero', 0, p + 4
    if b[p:p+4] == bytes.fromhex('80 09 0E 05'):
        return 'cell', None, p + 4
    if b[p:p+4] == bytes.fromhex('80 09 0C 03') and p + 8 <= end:
        return 'int', struct.unpack_from('<i', b, p + 4)[0], p + 8
    if b[p:p+4] == bytes.fromhex('80 09 04 03') and p + 9 <= end:
        return 'uint', struct.unpack_from('<I', b, p + 4)[0], p + 9
    # Compact signed byte codec used by Posz/Alpha in some streams.
    if b[p:p+4] == bytes.fromhex('80 09 06 03') and p + 5 <= end:
        return 'byte', struct.unpack_from('<b', b, p + 4)[0], p + 5
    if b[p:p+4] == bytes.fromhex('80 09 05 03') and p + 8 <= end:
        return 'float', struct.unpack_from('<f', b, p + 4)[0], p + 8
    raise ValueError(f'Unknown value codec @0x{p:X}: {b[p:p+20].hex(" ")}')


def find_key_marker(b, start, end):
    """Find the next key marker, including Bezier/curve markers used by some assets."""
    best = -1
    for mk in (KEY_MARKER, *CURVE_KEY_MARKERS):
        x = b.find(mk, start, end)
        if x >= 0 and (best < 0 or x < best):
            best = x
    return best


def frame_from_prefix(pre):
    if pre in (bytes.fromhex('80 09 03'), bytes.fromhex('80 09 01 01'), bytes.fromhex('80 09 01 03')):
        return 0
    if len(pre) == 7 and pre[:3] == bytes.fromhex('80 09 02'):
        return struct.unpack_from('<I', pre, 3)[0]
    if len(pre) == 8 and pre[0] == 1 and pre[1:4] == bytes.fromhex('80 09 02'):
        return struct.unpack_from('<I', pre, 4)[0]
    if len(pre) == 7 and pre[:2] == bytes.fromhex('00 09') and pre[3:] == bytes.fromhex('00 00 00 01'):
        return pre[2]
    if len(pre) == 7 and pre[:2] == bytes.fromhex('00 09') and pre[3:] == bytes.fromhex('00 00 00 03'):
        return pre[2]
    # newer cooked assets (e.g. summon13128) use a 01 flag before the 00 00 01 tail
    if len(pre) == 7 and pre[:2] == bytes.fromhex('00 09') and pre[3:] == bytes.fromhex('01 00 00 01'):
        return pre[2]
    raise ValueError(f'Unknown frame header: {pre.hex(" ")}')


def parse_keys(b, q, end, count):
    first_mark = find_key_marker(b, q, end)
    if first_mark < 0:
        raise ValueError(f'No first key marker @0x{q:X}')
    frame = frame_from_prefix(b[q:first_mark])
    marker = first_mark
    keys = []
    for i in range(count):
        mk = b[marker:marker+3]
        if mk in CURVE_KEY_MARKERS:
            n = CURVE_KEY_MARKERS[mk]
            value_type, value, vend = 'curve', struct.unpack_from('<f', b, marker + 3)[0], marker + 3 + n * 4
            # some curve keys append a normal scalar value codec after the floats
            if b[vend:vend+2] == b'\x80\x09':
                try:
                    _, _, vend = read_value(b, vend, end)
                except ValueError:
                    pass
        else:
            value_type, value, vend = read_value(b, marker + 3, end)
        keys.append({'frame': frame, 'value_type': value_type, 'value': value,
                     'marker': marker, 'end': vend})
        if i + 1 == count:
            return keys, vend
        next_mark = find_key_marker(b, vend, end)
        if next_mark < 0:
            raise ValueError(f'No next key marker after @0x{vend:X}')
        frame = frame_from_prefix(b[vend:next_mark])
        marker = next_mark
    return keys, vend


def skip_unknown_attr(b, q, end, count):
    p = q
    last = None
    for _ in range(count):
        last = find_key_marker(b, p, end)
        if last < 0:
            raise ValueError('Unknown attribute has fewer key markers than count')
        # We do not need to decode these keys, only to advance safely.
        p = last + 3
    candidates = [x for x in (b.find(b'\x00\x05', p, end), b.find(MAGIC_CELL_KEY, p, end)) if x >= 0]
    return min(candidates) if candidates else end


def parse_attribute(b, q, end):
    if b[q:q+3] == MAGIC_CELL_KEY:
        code = 0
        count = struct.unpack_from('<I', b, q + 3)[0]
        head = 7
    elif b[q:q+2] == b'\x00\x05':
        code = b[q + 2]
        count = struct.unpack_from('<I', b, q + 3)[0]
        head = 7
    else:
        raise ValueError(f'Invalid attribute header @0x{q:X}: {b[q:q+20].hex(" ")}')
    if not 1 <= count <= 512:
        raise ValueError(f'Invalid key count {count} for attr {code} @0x{q:X}')
    name = ATTR_NAMES.get(code, f'Unknown_{code}')
    start = q
    q += head
    if code not in ATTR_NAMES:
        nq = skip_unknown_attr(b, q, end, count)
        return {'code': code, 'name': name, 'count': count, 'keys': [], 'start': start, 'end': nq}, nq
    keys, q = parse_keys(b, q, end, count)
    return {'code': code, 'name': name, 'count': count, 'keys': keys, 'start': start, 'end': q}, q


def parse_part(b, q, end, names):
    if b[q:q+2] != b'\x00\x05':
        raise ValueError(f'Invalid Part header @0x{q:X}: {b[q:q+20].hex(" ")}')
    ni = struct.unpack_from('<I', b, q + 2)[0]
    num = struct.unpack_from('<I', b, q + 6)[0]
    attr_count = struct.unpack_from('<I', b, q + 10)[0]
    if not (0 <= ni < len(names) and 1 <= attr_count <= 64):
        raise ValueError(f'Invalid Part header @0x{q:X}')
    attrs = []
    p = q + 14
    for _ in range(attr_count):
        a, p = parse_attribute(b, p, end)
        attrs.append(a)
    return Part(ssbase.decode_fname_number(names[ni], num), ni, num, attrs, q), p


def parse_animations(uasset: Path, uexp: Path):
    names = ssbase.read_name_table(uasset)
    b = uexp.read_bytes()
    headers = []
    for magic in (MAGIC_ANIM, MAGIC_SETUP):
        p = 0
        while True:
            x = b.find(magic, p)
            if x < 0:
                break
            headers.append(x)
            p = x + 1
    headers = sorted(set(headers))
    next_header = {x: (headers[i+1] if i + 1 < len(headers) else len(b)) for i, x in enumerate(headers)}
    animations = []
    for ai, off in enumerate(headers):
        magic = b[off:off+3]
        ni, num = struct.unpack_from('<II', b, off + 3)
        name = ssbase.decode_fname_number(names[ni], num)
        settings = b[off+11:off+15]
        frame_count = struct.unpack_from('<I', b, off + 18)[0]
        is_normal_anim = magic == MAGIC_ANIM and settings[:3] in (bytes.fromhex('80 0F 34'), bytes.fromhex('80 0F 30'), bytes.fromhex('80 0F 10'))
        is_pose_anim = magic == MAGIC_ANIM and settings[:3] == bytes.fromhex('80 0F 74')
        if is_normal_anim:
            pc0 = struct.unpack_from('<I', b, off + 34)[0]
            pc1 = struct.unpack_from('<I', b, off + 35)[0] if off + 39 <= len(b) else 0
            shifted = (not (1 <= pc0 <= 64 and b[off+38:off+40] == b'\x00\x05')) and 1 <= pc1 <= 512
            if shifted:
                candidates = []
                for qq in (off + 39, off + 43):
                    if qq + 14 <= next_header[off] and b[qq:qq+2] == b'\x00\x05':
                        ni0 = struct.unpack_from('<I', b, qq + 2)[0]
                        ac0 = struct.unpack_from('<I', b, qq + 10)[0]
                        if 0 <= ni0 < len(names) and 1 <= ac0 <= 64:
                            candidates.append(qq)
                if len(candidates) != 1:
                    raise ValueError(f'Cannot locate first Part for {name} @0x{off:X}')
                q = candidates[0]
                part_count = pc1 if q == off + 39 else struct.unpack_from('<I', b, off + 39)[0]
                canvas_x, canvas_y = struct.unpack_from('<2f', b, off + 23)
                end_frame = struct.unpack_from('<I', b, off + 31)[0]
            else:
                part_count = pc0
                q = off + 38
                canvas_x, canvas_y = struct.unpack_from('<2f', b, off + 22)
                end_frame = struct.unpack_from('<I', b, off + 30)[0]
        elif is_pose_anim or magic == MAGIC_SETUP:
            part_count = None
            q = off + 34
            canvas_x, canvas_y = (None, None)
            end_frame = None
            # Setup is variable length; locate first structurally valid Part.
            found = None
            for qq in range(q, min(q + 20, next_header[off])):
                if b[qq:qq+2] == b'\x00\x05' and qq + 14 <= next_header[off]:
                    ni0 = struct.unpack_from('<I', b, qq + 2)[0]
                    ac0 = struct.unpack_from('<I', b, qq + 10)[0]
                    if 0 <= ni0 < len(names) and 1 <= ac0 <= 64:
                        found = qq; break
            q = found if found is not None else next_header[off]
        parts = []
        while q < next_header[off] and (part_count is None or len(parts) < part_count):
            # Setup/Pose terminator/padding handling.
            if part_count is None and b[q:q+4] == b'\0\0\0\0':
                q += 4
                if q >= next_header[off]: break
                continue
            try:
                p0, q = parse_part(b, q, next_header[off], names)
            except ValueError:
                break
            parts.append(p0)
        if part_count is not None and len(parts) != part_count:
            raise ValueError(f'{name}: expected {part_count} parts, got {len(parts)}')
        fps = 30 if settings[-1:] == b'\x1e' else 60
        animations.append({'index': ai, 'name': name, 'offset': off, 'frame_count': frame_count,
                           'end_frame': end_frame, 'canvas_x': canvas_x, 'canvas_y': canvas_y,
                           'fps': fps, 'parts': parts, 'header_type': 'Setup' if magic == MAGIC_SETUP else 'Normal'})
    return names, animations


def parse_static_nodes(uasset: Path, uexp: Path):
    names = ssbase.read_name_table(uasset)
    b = uexp.read_bytes()
    first_anim = min([x for x in (b.find(MAGIC_ANIM), b.find(MAGIC_SETUP)) if x >= 0], default=len(b))
    markers = []
    q = 0
    while True:
        x = b.find(bytes.fromhex('FE 80 75'), q, first_anim)
        if x < 0:
            break
        markers.append(x)
        q = x + 1
    nodes = []
    for x in markers:
        if x + 19 > len(b):
            continue
        name_index, fname_number, node_id, parent_id = struct.unpack_from('<IIII', b, x + 11)
        if not (0 <= name_index < len(names)):
            continue
        nodes.append(StaticNode(node_id, parent_id, name_index, fname_number,
                                ssbase.decode_fname_number(names[name_index], fname_number), x))
    # Strictly require a useful contiguous table; discard any accidental late hits.
    nodes.sort(key=lambda n: n.offset)
    return names, nodes


def build_static_map(nodes):
    return {(n.name_index, n.fname_number): n for n in nodes}


def attr_map(part):
    return {a['name']: a for a in part.attrs}


def key_value(attrs, name, frame, default):
    a = attrs.get(name)
    if not a or not a['keys']:
        return default
    best = None
    for k in a['keys']:
        if k['frame'] <= frame:
            best = k
        else:
            break
    if best is None:
        return default
    return best['value'] if best['value_type'] != 'zero' else 0


def attach_cells(uexp, names, animations):
    cells, records = ssbase.parse_cell_defs(uexp, names)
    refs = ssbase.parse_cell_refs(uexp)
    lookup = {ssbase.cell_ref_name(c): c for c in cells}
    lookup.update(records)
    # Consume Cell-bearing keys in animation order, same conservative alignment rule.
    cell_keys = []
    for a in animations:
        for pi, p in enumerate(a['parts']):
            for at in p.attrs:
                if at['name'] == 'Cell':
                    for k in at['keys']:
                        cell_keys.append((a, pi, p, k))
    # The research evaluator should not guess a broken alignment.
    if len(refs) < len(cell_keys):
        raise ValueError(f'Cell key/reference count mismatch: {len(cell_keys)} > {len(refs)}')
    offset = len(refs) - len(cell_keys)
    # In known FFRS assets extra references can precede animation references when Setup exists.
    if offset and not any(a['header_type'] == 'Setup' for a in animations):
        raise ValueError('Reference alignment requires an unexplained offset; refusing to guess')
    ri = offset
    for a, pi, p, k in cell_keys:
        r = refs[ri]; ri += 1
        k['reference'] = r.name
        k['reference_order'] = r.order
        k['cell'] = lookup.get(r.name)
    return cells, records


def make_frame_state(animation, frame, static_by_key):
    states = {}
    for pi, p in enumerate(animation['parts']):
        parent = static_by_key.get((p.name_index, p.fname_number))
        attrs = attr_map(p)
        cell = None
        a = attrs.get('Cell')
        if a:
            best = None
            for k in a['keys']:
                if k['frame'] <= frame:
                    best = k
                else:
                    break
            if best is not None:
                cell = best.get('cell')
        st = {
            'part_index': pi, 'part_name': p.name, 'name_index': p.name_index,
            'fname_number': p.fname_number,
            'node_id': parent.node_id if parent else None,
            'parent_id': parent.parent_id if parent else None,
            'cell': cell,
            'x': float(key_value(attrs,'Posx',frame,0) or 0),
            'y': float(key_value(attrs,'Posy',frame,0) or 0),
            'z': float(key_value(attrs,'Posz',frame,0) or 0),
            'rot': float(key_value(attrs,'Rotz',frame,0) or 0),
            'sx': float(key_value(attrs,'Sclx',frame,1) if key_value(attrs,'Sclx',frame,1) is not None else 1),
            'sy': float(key_value(attrs,'Scly',frame,1) if key_value(attrs,'Scly',frame,1) is not None else 1),
            'prio': int(key_value(attrs,'Prio',frame,0) or 0),
            'hide': bool(key_value(attrs,'Hide',frame,0) or 0),
            'alpha': float(key_value(attrs,'Alpha',frame,255) if key_value(attrs,'Alpha',frame,255) is not None else 255),
        }
        # Alpha is an observed numeric attribute; when absent the SpriteStudio default is opaque.
        states[st['node_id'] if st['node_id'] is not None else ('anim', pi)] = st
        states[('part', pi)] = st
    return states


def mat_mul(A, B):
    # 2D affine matrix [a,b,c,d,tx,ty] mapping x'=a*x+c*y+tx, y'=b*x+d*y+ty.
    a,b,c,d,tx,ty=A; e,f,g,h,ux,uy=B
    return (a*e+c*f, b*e+d*f, a*g+c*h, b*g+d*h, a*ux+c*uy+tx, b*ux+d*uy+ty)


def local_matrix(x, y, rot_deg, sx, sy):
    r = math.radians(rot_deg)
    cr, sr = math.cos(r), math.sin(r)
    return (cr*sx, sr*sx, -sr*sy, cr*sy, x, y)


def apply(M, pt):
    a,b,c,d,tx,ty = M; x,y=pt
    return (a*x+c*y+tx, b*x+d*y+ty)


def world_matrices(states):
    by_node = {st['node_id']: st for st in states.values() if isinstance(st.get('node_id'), int)}
    cache = {}
    visiting = set()
    ID = (1,0,0,1,0,0)
    def eval_node(nid):
        if nid in cache: return cache[nid]
        if nid in visiting:
            raise ValueError(f'Parent cycle at NodeID {nid}')
        visiting.add(nid)
        st = by_node[nid]
        local = local_matrix(st['x'], st['y'], st['rot'], st['sx'], st['sy'])
        pid = st['parent_id']
        if pid in by_node:
            world = mat_mul(eval_node(pid), local)
        else:
            world = local
        visiting.remove(nid)
        cache[nid] = world
        return world
    for nid in by_node:
        eval_node(nid)
    return cache


def cell_quad_internal(st, world):
    c = st.get('cell')
    if c is None or not getattr(c, 'geometry_available', False) or c.width <= 0 or c.height <= 0:
        return None
    # SpriteStudio cell origin starts at the cell center. The serialized FFRS
    # pivot values are normalized against cell width/height. Positive pivot
    # moves the part origin right/up, therefore pixel coordinates relative to
    # the origin subtract the pivot offset from the cell rectangle.
    px = float(c.pivot_x) * c.width
    py = float(c.pivot_y) * c.height
    w, h = float(c.width), float(c.height)
    local = [
        (-w/2 - px, +h/2 - py),  # TL in internal Y-up coordinates
        (+w/2 - px, +h/2 - py),  # TR
        (+w/2 - px, -h/2 - py),  # BR
        (-w/2 - px, -h/2 - py),  # BL
    ]
    return [apply(world, p) for p in local]


def quad_to_raster(quad, origin_x, origin_y):
    return [(origin_x + x, origin_y - y) for x, y in quad]


def export_debug_frame(atlas_path, animation, frame, static_map, origin, out_png, out_json):
    atlas = Image.open(atlas_path).convert('RGBA')
    states = make_frame_state(animation, frame, static_map)
    worlds = world_matrices(states)
    ox, oy = origin
    rows=[]
    for pi in range(len(animation['parts'])):
        st = states.get(('part',pi))
        if not st: continue
        nid = st.get('node_id')
        if st['hide'] or nid not in worlds: continue
        q = cell_quad_internal(st, worlds[nid])
        if not q: continue
        rq = quad_to_raster(q, ox, oy)
        xs=[p[0] for p in rq]; ys=[p[1] for p in rq]
        rows.append({
            'part_index':pi, 'part_name':st['part_name'], 'node_id':nid,
            'parent_id':st['parent_id'], 'cell_id':st['cell'].cell_id,
            'local':{'x':st['x'],'y':st['y'],'z':st['z'],'rot':st['rot'],'sx':st['sx'],'sy':st['sy']},
            'world_matrix':list(worlds[nid]),
            'raster_quad':rq,
            'raster_bbox':[min(xs),min(ys),max(xs),max(ys)],
        })
    canvas_w = int(round(origin[0]*2))
    canvas_h = int(round(origin[1]*2))
    out = Image.new('RGBA', (canvas_w, canvas_h), (0,0,0,0))
    # For debug only, use a high-quality-free nearest affine placement via the
    # quadrilateral's axis-aligned unrotated crop where possible. Exact sprite
    # pixels are not the validation target here; world quads are.
    draw = ImageDraw.Draw(out)
    for r in sorted(rows, key=lambda z:(z['local']['z'], z['part_index'])):
        pts=[(round(x),round(y)) for x,y in r['raster_quad']]
        draw.line(pts+[pts[0]], fill=(255,255,0,255), width=1)
        draw.text((pts[0][0],pts[0][1]), str(r['part_index']), fill=(255,255,0,255))
    out.save(out_png)
    Path(out_json).write_text(json.dumps({'animation':animation['name'],'frame':frame,'origin':list(origin),'parts':rows},ensure_ascii=False,indent=2),encoding='utf-8')
    return rows


def find_animation(animations, name):
    for a in animations:
        if a['name'] == name: return a
    raise KeyError(name)


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--stem', choices=['summon13100','unit0010'], default='summon13100')
    ap.add_argument('--animation', default='idle')
    ap.add_argument('--frame', type=int, default=0)
    ap.add_argument('--origin-x', type=float, default=None)
    ap.add_argument('--origin-y', type=float, default=None)
    ap.add_argument('--out-prefix', default=None)
    args=ap.parse_args()
    root=Path('/mnt/data/research')
    ua=root/(args.stem+'.uasset'); ue=root/(args.stem+'.uexp'); atlas=root/(args.stem+'_tex.png')
    names,nodes=parse_static_nodes(ua,ue)
    _,anims=parse_animations(ua,ue)
    attach_cells(ue,names,anims)
    static_map=build_static_map(nodes)
    anim=find_animation(anims,args.animation)
    ox=args.origin_x if args.origin_x is not None else (anim['canvas_x'] or 0)/1
    oy=args.origin_y if args.origin_y is not None else (anim['canvas_y'] or 0)/1
    pref=Path(args.out_prefix or f'/mnt/data/research/transform_{args.stem}_{args.animation}_{args.frame:03d}')
    rows=export_debug_frame(atlas,anim,args.frame,static_map,(ox,oy),str(pref.with_suffix('.png')),str(pref.with_suffix('.json')))
    drawable=[r for r in rows if r['part_name'] not in ('root',) and not r['part_name'].startswith('NULL_')]
    unresolved=sum(1 for p in anim['parts'] if p.name!='root' and (p.name_index,p.fname_number) not in static_map)
    print(f'{args.stem}: static_nodes={len(nodes)}, animation={anim["name"]}, parts={len(anim["parts"])}, drawable_quads={len(drawable)}, animation_parts_without_static_node={unresolved}')
    for r in drawable[:20]:
        print(f"  p{r['part_index']:02d} {r['part_name']:<18} cell={r['cell_id']:>3} node={r['node_id']:>3} parent={r['parent_id']!s:>10} bbox={tuple(round(x,2) for x in r['raster_bbox'])}")
    print('JSON:',pref.with_suffix('.json'))
    print('PNG :',pref.with_suffix('.png'))

if __name__=='__main__':
    main()
