#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FFRS Sprite <-> PSD core for the v1.0 integrated tool.

Core goals
----------
* UE5 .uasset/.uexp are the only animation/geometry evidence.
* _tex is used for preview; _normal/_mreo share the same Cell geometry.
* Parent Matrix + Cell Pivot is evaluated per frame.
* PSD layer order is not used for recovery.
* Optional Safe 1px PSD adds a solid black 1px border around each layer.
* Recovery strips that border from geometry, then maps PSD pixels back to the
  original Cell through the same forward nearest-neighbour rasterizer.

The PSD reader supports the layer structure emitted by this tool and common
Photoshop PSD layer records using raw or PackBits/RLE channel compression.
"""
from __future__ import annotations
import csv
import json
import math
import re
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from collections import defaultdict
from typing import Optional, Iterable

import numpy as np
from PIL import Image, ImageDraw
import cv2

import sprite_slice_analyzer_multitex as ssa
from v3inspect import transform_eval as te

APP_VERSION = "1.1.24"
SAFE_PAD = 1
SAFE_COLOR = (0, 0, 0, 255)
MAX_PSD_LAYERS = 7900

@dataclass
class LayerRender:
    animation: str
    frame: int
    part_index: int
    part_name: str
    name_index: int
    fname_number: int
    node_id: int
    parent_id: Optional[int]
    cell_id: int
    atlas_rect: list
    local: dict
    world_matrix: tuple
    raster_quad: list
    bbox: list
    image: Image.Image
    # Cropping rectangle inside the temporary warp canvas. Kept for mapping.
    warp_origin: tuple
    warp_bbox: tuple
    source_size: tuple


def alpha_to_u8(v):
    if v is None:
        return 255
    x = float(v)
    if 0.0 <= x <= 1.0:
        return max(0, min(255, round(x * 255.0)))
    return max(0, min(255, round(x)))


def source_to_screen_affine(cell, world, origin):
    a, b, c, d, tx, ty = world
    ox, oy = origin
    w, h = float(cell.width), float(cell.height)
    px = float(cell.pivot_x) * w
    py = float(cell.pivot_y) * h
    # Internal space is Y-up. Raster screen is Y-down.
    A = a; C = -c
    Tx = ox + a * (-w / 2 - px) + c * (h / 2 - py) + tx
    B = -b; D = d
    Ty = oy + b * (w / 2 + px) - d * (h / 2 - py) - ty
    return np.array([[A, C, Tx], [B, D, Ty]], dtype=np.float64)


def alpha_over(dst, src):
    sa = src[..., 3:4].astype(np.float32) / 255.0
    da = dst[..., 3:4].astype(np.float32) / 255.0
    oa = sa + da * (1.0 - sa)
    out = np.zeros_like(dst, dtype=np.float32)
    den = np.maximum(oa, 1e-8)
    out[..., :3] = (
        src[..., :3].astype(np.float32) * sa
        + dst[..., :3].astype(np.float32) * da * (1.0 - sa)
    ) / den
    out[..., 3:4] = oa * 255.0
    return np.clip(out, 0, 255).astype(np.uint8)


def infer_sort_mode(anim, static_map):
    # Same conservative fallback used by the research renderer. The serialized
    # SpriteStudio SortMode enum itself is not required for recovery.
    evidence = []
    for frame in range(max(1, int(anim.get("frame_count") or 0))):
        d = []
        states = te.make_frame_state(anim, frame, static_map)
        worlds = te.world_matrices(states)
        for pi in range(len(anim["parts"])):
            st = states.get(("part", pi))
            if not st or st["part_name"] == "root" or st["part_name"].startswith("NULL_"):
                continue
            nid = st.get("node_id"); c = st.get("cell")
            if st.get("hide") or nid not in worlds or c is None or not getattr(c, "geometry_available", False):
                continue
            d.append(st)
        if len(d) < 2:
            continue
        z = sorted({s["z"] for s in d}); p = sorted({s["prio"] for s in d})
        if len(z) > 1 or len(p) > 1:
            evidence.append((frame, len(z) > 1, len(p) > 1))
    zvar = sum(x[1] for x in evidence)
    pvar = sum(x[2] for x in evidence)
    if pvar and not zvar:
        mode = "priority"
    elif zvar and not pvar:
        mode = "z"
    elif pvar and zvar:
        mode = "priority"
    else:
        mode = "part"
    return {"mode": mode, "z_variable_frames": zvar, "priority_variable_frames": pvar,
            "evidence_count": len(evidence),
            "reason": "fallback inference; PSD recovery is independent of layer order"}


def sorted_layers(rows, mode):
    if mode == "priority":
        return sorted(rows, key=lambda r: (r.local["prio"], r.part_index))
    if mode == "z":
        return sorted(rows, key=lambda r: (-r.local["z"], r.part_index))
    return sorted(rows, key=lambda r: r.part_index)


def build_resource(uasset: Path):
    return ssa.resource_for(uasset)


def load_resource(resource):
    names, nodes = te.parse_static_nodes(resource.uasset, resource.uexp)
    _, animations = te.parse_animations(resource.uasset, resource.uexp)
    te.attach_cells(resource.uexp, names, animations)
    static_map = te.build_static_map(nodes)
    texture_cache={}
    for k,v in resource.textures().items():
        if v and v.exists():
            im=Image.open(v).convert("RGBA")
            texture_cache[k]={"image":im,"array":np.asarray(im)}
    try: resource._texture_cache=texture_cache
    except Exception: pass
    sort_cache={}
    for a in animations:
        if a.get("header_type")!="Setup" and a.get("frame_count"):
            sort_cache[a["name"]]=infer_sort_mode(a, static_map)
    return {"names": names, "nodes": nodes, "animations": animations, "static_map": static_map,
            "texture_cache": texture_cache, "sort_cache": sort_cache}


def animation_by_name(data, name):
    for a in data["animations"]:
        if a["name"] == name and a.get("header_type") != "Setup":
            return a
    raise KeyError(name)


def drawable_rows(resource, data, animation, frame, texture_kind="tex"):
    texture = resource.textures().get(texture_kind) or resource.tex or resource.normal or resource.mreo
    if texture is None:
        raise FileNotFoundError("No texture available for rendering")
    cache=getattr(resource,"_texture_cache",None)
    if cache is None:
        atlas=Image.open(texture).convert("RGBA"); src_all=np.asarray(atlas)
    else:
        key=next((k for k,p in resource.textures().items() if p==texture),texture_kind)
        item=cache.get(key)
        if item is None:
            atlas=Image.open(texture).convert("RGBA"); src_all=np.asarray(atlas)
        else:
            atlas=item["image"]; src_all=item["array"]
    states = te.make_frame_state(animation, frame, data["static_map"])
    worlds = te.world_matrices(states)
    cw = int(round(animation["canvas_x"] or atlas.width))
    ch = int(round(animation["canvas_y"] or atlas.height))
    origin = ((animation["canvas_x"] or cw) / 2.0, (animation["canvas_y"] or ch) / 2.0)
    rows = []

    for pi in range(len(animation["parts"])):
        st = states.get(("part", pi))
        if not st or st["part_name"] == "root" or st["part_name"].startswith("NULL_"):
            continue
        nid = st.get("node_id"); c = st.get("cell")
        if st.get("hide") or nid not in worlds or c is None:
            continue
        if not getattr(c, "geometry_available", False) or c.width <= 0 or c.height <= 0:
            continue
        x0, y0, w, h = map(int, (c.x, c.y, c.width, c.height))
        if x0 < 0 or y0 < 0 or x0 + w > src_all.shape[1] or y0 + h > src_all.shape[0]:
            continue

        src = src_all[y0:y0+h, x0:x0+w].copy()
        au8 = alpha_to_u8(st.get("alpha"))
        if au8 != 255:
            src[..., 3] = ((src[..., 3].astype(np.uint16) * au8 + 127) // 255).astype(np.uint8)

        M = source_to_screen_affine(c, worlds[nid], origin)
        q = te.cell_quad_internal(st, worlds[nid])
        rq = te.quad_to_raster(q, *origin)
        xs = [p[0] for p in rq]; ys = [p[1] for p in rq]
        xmin = max(0, int(math.floor(min(xs))) - 2)
        ymin = max(0, int(math.floor(min(ys))) - 2)
        xmax = min(cw, int(math.ceil(max(xs))) + 3)
        ymax = min(ch, int(math.ceil(max(ys))) + 3)
        if xmax <= xmin or ymax <= ymin:
            continue
        LM = M.copy(); LM[0, 2] -= xmin; LM[1, 2] -= ymin
        warped = cv2.warpAffine(
            src, LM.astype(np.float32), (xmax-xmin, ymax-ymin),
            flags=cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT,
            borderValue=(0, 0, 0, 0),
        )
        tmp = Image.fromarray(warped, "RGBA")
        bb = tmp.getchannel("A").getbbox()
        # Keep referenced Cells even when a replacement atlas makes their
        # source rectangle fully transparent. The empty layer preserves the
        # Cell identity/manifest entry needed by resource-PSD recovery.
        if not bb:
            bb = (0, 0, tmp.width, tmp.height)
        crop = tmp.crop(bb)
        left, top = xmin + bb[0], ymin + bb[1]
        rows.append(LayerRender(
            animation=animation["name"], frame=int(frame), part_index=int(pi),
            part_name=st["part_name"], name_index=int(st["name_index"]),
            fname_number=int(st["fname_number"]), node_id=int(nid),
            parent_id=int(st["parent_id"]) if st.get("parent_id") is not None else None,
            cell_id=int(c.cell_id), atlas_rect=[x0, y0, w, h],
            local={"x": st["x"], "y": st["y"], "z": st["z"], "rot": st["rot"],
                   "sx": st["sx"], "sy": st["sy"], "prio": st["prio"],
                   "hide": bool(st["hide"]), "alpha": st.get("alpha")},
            world_matrix=tuple(worlds[nid]),
            raster_quad=[[float(x), float(y)] for x, y in rq],
            bbox=[int(left), int(top), int(crop.width), int(crop.height)],
            image=crop,
            warp_origin=(xmin, ymin), warp_bbox=(xmin, ymin, xmax-xmin, ymax-ymin),
            source_size=(w, h),
        ))
    return rows, [cw, ch], list(origin), atlas.size


def render_animation_frame(resource, data, animation_name, frame, texture_kind="tex", sort_mode="auto"):
    animation = animation_by_name(data, animation_name)
    inference = data.get("sort_cache",{}).get(animation_name) or infer_sort_mode(animation, data["static_map"])
    mode = inference["mode"] if sort_mode == "auto" else sort_mode
    rows, canvas_size, origin, atlas_size = drawable_rows(resource, data, animation, int(frame), texture_kind)
    ordered = sorted_layers(rows, mode)
    cw, ch = canvas_size
    canvas = np.zeros((ch, cw, 4), dtype=np.uint8)
    for r in ordered:
        x, y, w, h = r.bbox
        if x < 0 or y < 0 or x+w > cw or y+h > ch:
            continue
        src = np.asarray(r.image)
        canvas[y:y+h, x:x+w] = alpha_over(canvas[y:y+h, x:x+w], src)
    return Image.fromarray(canvas, "RGBA"), {
        "animation": animation_name, "frame": int(frame), "canvas": canvas_size,
        "origin": origin, "sort_mode": mode, "sort_inference": inference,
        "layer_count": len(ordered), "atlas_size": list(atlas_size),
        "layers": ordered,
    }


def layer_name(r: LayerRender):
    return f"Part_{r.part_index:03d}__Cell_{r.cell_id}__{r.part_name}"


def add_safe(img, pad=SAFE_PAD):
    a = np.asarray(img.convert("RGBA"))
    h, w = a.shape[:2]
    out = np.empty((h + 2*pad, w + 2*pad, 4), dtype=np.uint8)
    out[:] = SAFE_COLOR
    out[pad:pad+h, pad:pad+w] = a
    return Image.fromarray(out, "RGBA")


def add_cell_number_layer(cell_id, left, top):
    """Create a separate, non-destructive visible Cell-number badge layer.

    The number is the Cell ID used by the Analyzer's crops_numbered export.
    It is deliberately a separate non-Part layer, so PSD -> Sprite recovery
    ignores the label and never writes annotation pixels into the source atlas.
    """
    text = str(int(cell_id))
    try:
        from PIL import ImageFont
        font = ImageFont.truetype("arial.ttf", 12)
    except Exception:
        from PIL import ImageFont
        font = ImageFont.load_default()
    probe = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    d = ImageDraw.Draw(probe)
    bb = d.textbbox((0, 0), text, font=font)
    tw, th = max(1, bb[2]-bb[0]), max(1, bb[3]-bb[1])
    pad = 3
    badge = Image.new("RGBA", (tw+pad*2, th+pad*2), (0, 0, 0, 0))
    bd = ImageDraw.Draw(badge)
    bd.rectangle((0, 0, badge.width-1, badge.height-1), fill=(0, 0, 0, 220))
    bd.text((pad-bb[0], pad-bb[1]), text, font=font, fill=(255, 255, 0, 255))
    return {"name": f"__CellNumber_{int(cell_id):04d}", "img": badge,
            "left": int(left), "top": int(top), "visible": True}

# ---------------- PSD writer ----------------
def be_i32(v): return struct.pack(">i", int(v))
def be_i16(v): return struct.pack(">h", int(v))
def be_u16(v): return struct.pack(">H", int(v) & 0xFFFF)
def be_u32(v): return struct.pack(">I", int(v) & 0xFFFFFFFF)

def pascal(s):
    b = str(s).encode("utf-8", "replace")[:255]
    b = bytes([len(b)]) + b
    return b + b"\0" * ((-len(b)) % 4)

def extra_section(name, divider=None, divider_key=None, divider_subtype=None):
    # Layer extra data: mask data, blending ranges, Pascal name, then
    # Additional Layer Information.  Photoshop expects folder section
    # dividers to follow the canonical order used by its own writer: a hidden
    # type-3 bounding divider before the children, followed by a type-1/2
    # folder record carrying the actual group name.
    e = be_u32(0) + be_u32(0) + pascal(name)
    if divider is not None:
        payload = be_u32(divider)
        if divider_key is not None:
            payload += b"8BIM" + bytes(str(divider_key).encode('latin1')[:4]).ljust(4, b' ')
            if divider_subtype is not None:
                payload += be_u32(divider_subtype)
        e += b"8BIMlsct" + be_u32(len(payload)) + payload
    return e

def layer_record(layer):
    im = layer.get("img")
    if im is None:
        top = left = bottom = right = 0
        channels = []
    else:
        left = int(layer.get("left", 0)); top = int(layer.get("top", 0))
        right = left + im.width; bottom = top + im.height
        raw = im.convert("RGBA").tobytes()
        channels = [(-1, raw[3::4]), (0, raw[0::4]), (1, raw[1::4]), (2, raw[2::4])]
    r = be_i32(top)+be_i32(left)+be_i32(bottom)+be_i32(right)+be_u16(len(channels))
    for cid, data in channels:
        r += be_i16(cid) + be_u32(2 + len(data))
    visible = bool(layer.get("visible", True))
    is_group = layer.get("divider") in (1, 2, 3)
    # The layer-record blend mode remains normal for section-divider records;
    # the actual group "pass through" behavior is carried by the lsct key.
    blend_key = str(layer.get("blend_key") or "norm")[:4].encode('latin1').ljust(4, b' ')
    # Photoshop folder/group records use "pass" as their blend mode.  The
    # pixel-data-irrelevant flag is appropriate for all section-divider
    # records because they carry no drawable pixels.
    flags = 0x08 | (0x10 if is_group else 0)
    r += b"8BIM" + blend_key + bytes([255 if visible else 0]) + b"\0" + bytes([flags]) + b"\0"
    e = extra_section(layer["name"], layer.get("divider"),
                      layer.get("divider_key"), layer.get("divider_subtype"))
    r += be_u32(len(e)) + e
    payload = []
    for _cid, data in channels:
        payload.append(be_u16(0) + data)  # raw / uncompressed
    return r, b"".join(payload)

def write_psd(path: Path, width, height, layers):
    records=[]; data=[]
    for layer in layers:
        a,b = layer_record(layer); records.append(a); data.append(b)
    li = be_i16(len(layers)) + b"".join(records) + b"".join(data)
    lm = be_u32(len(li)) + li + be_u32(0)
    header = b"8BPS"+be_u16(1)+b"\0"*6+be_u16(4)+be_u32(height)+be_u32(width)+be_u16(8)+be_u16(3)
    # Empty composite RGBA image. Photoshop still opens the Layer section.
    transparent = be_u16(0) + bytes(width*height)
    out = header + be_u32(0) + be_u32(0) + be_u32(len(lm)) + lm + transparent*4
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(out)

# ---------------- PSD reader ----------------
def _read_pascal(data, p):
    if p >= len(data): return "", p
    n = data[p]; p += 1
    raw = data[p:p+n]; p += n
    p += (-((1+n))) % 4
    return raw.decode("utf-8", "replace"), p

def _decode_packbits_row(buf, expected):
    out=bytearray(); p=0
    while p < len(buf) and len(out) < expected:
        n=struct.unpack("b",bytes([buf[p]]))[0]; p+=1
        if n >= 0:
            cnt=n+1; out += buf[p:p+cnt]; p += cnt
        elif n != -128:
            cnt=1-n
            if p >= len(buf): break
            out += buf[p:p+1]*cnt; p += 1
    return bytes(out[:expected])

def _decode_channel(blob, width, height):
    if len(blob) < 2: return np.zeros((height,width),dtype=np.uint8)
    comp = struct.unpack_from(">H",blob,0)[0]
    if comp == 0:
        raw = blob[2:2+width*height]
        return np.frombuffer(raw,dtype=np.uint8).copy().reshape((height,width))
    if comp == 1:
        nrows=height
        need=2*nrows
        if len(blob) < 2+need: return np.zeros((height,width),dtype=np.uint8)
        lengths=struct.unpack_from(f">{nrows}H",blob,2)
        p=2+need; arr=np.empty(width*height,dtype=np.uint8); q=0
        for ln in lengths:
            row=_decode_packbits_row(blob[p:p+ln],width); p+=ln
            if len(row)<width: row=row+b"\0"*(width-len(row))
            arr[q:q+width]=np.frombuffer(row,dtype=np.uint8); q+=width
        return arr.reshape((height,width))
    if comp in (2,3):
        # Layer ZIP data is uncommon but valid in newer PSDs; channel payload
        # is a complete zlib stream after the 2-byte compression marker.
        try:
            raw=zlib.decompress(blob[2:])
            if comp==3:
                # prediction undo for 8-bit channels
                a=np.frombuffer(raw,dtype=np.uint8).copy().reshape((height,width))
                for y in range(height):
                    for x in range(1,width): a[y,x]=(int(a[y,x])+int(a[y,x-1]))&255
                return a
            return np.frombuffer(raw,dtype=np.uint8).copy().reshape((height,width))
        except Exception:
            pass
    raise ValueError(f"Unsupported PSD channel compression {comp}")

def _extra_info(extra):
    div=None; uni_name=None
    idx=extra.find(b"8BIMlsct")
    if idx>=0 and idx+16<=len(extra):
        try: div=struct.unpack_from(">I",extra,idx+12)[0]
        except Exception: pass
    idx=extra.find(b"8BIMluni")
    if idx>=0 and idx+12<=len(extra):
        try:
            ln=struct.unpack_from(">I",extra,idx+8)[0]
            block=extra[idx+12:idx+12+ln]
            if len(block)>=4:
                n=struct.unpack_from(">I",block,0)[0]; raw=block[4:4+2*n]
                uni_name=raw.decode("utf-16be","replace")
        except Exception: pass
    return div,uni_name

def read_psd_layers(path: Path):
    b=Path(path).read_bytes()
    if b[:4] != b"8BPS": raise ValueError("Not a PSD file")
    version=struct.unpack_from(">H",b,4)[0]
    if version != 1: raise ValueError("Only PSD version 1 is supported")
    channels,height,width,depth,color=struct.unpack_from(">HIIHH",b,12)
    if depth != 8: raise ValueError("Only 8-bit PSD is supported")
    p=26
    for _ in range(2):
        ln=struct.unpack_from(">I",b,p)[0]; p+=4+ln
    lm_len=struct.unpack_from(">I",b,p)[0]; p+=4
    lm_end=p+lm_len
    if lm_len < 4: return {"width":width,"height":height,"layers":[]}
    info_len=struct.unpack_from(">I",b,p)[0]; p+=4
    info_start=p; info_end=p+info_len
    count=struct.unpack_from(">h",b,p)[0]; p+=2
    records=[]
    for _ in range(abs(count)):
        rec_start=p
        top,left,bottom,right=struct.unpack_from(">iiii",b,p)
        nch=struct.unpack_from(">H",b,p+16)[0]
        q=p+18+6*nch
        if b[q:q+4] != b"8BIM": raise ValueError("Unsupported PSD blend signature")
        blend=b[q+4:q+8]; opacity=b[q+8]; flags=b[q+11]; q+=12
        extra_len=struct.unpack_from(">I",b,q)[0]; q+=4
        extra=b[q:q+extra_len]
        q += extra_len
        div,uni=_extra_info(extra)
        # The extra section contains mask/blending-range/layer-name; the
        # human-readable layer name is the Pascal string after those subfields.
        extra_content=extra
        ep=0
        if len(extra_content)>=4:
            mask_len=struct.unpack_from(">I",extra_content,ep)[0]; ep+=4+mask_len
        if ep+4<=len(extra_content):
            blend_len=struct.unpack_from(">I",extra_content,ep)[0]; ep+=4+blend_len
        name=""
        if ep<len(extra_content):
            name,_=_read_pascal(extra_content,ep)
        if uni: name=uni
        records.append({"top":top,"left":left,"bottom":bottom,"right":right,
                        "width":max(0,right-left),"height":max(0,bottom-top),
                        "nch":nch,"blend":blend.decode("latin1","replace"),"opacity":opacity,
                        "flags":flags,"name":name,"divider":div,"record_start":rec_start,
                        "record_end":q})
        p=q
    if p>info_end: raise ValueError("PSD layer info exceeds its declared length")
    data_cursor=(records[-1]["record_end"] if records else info_start+2)
    for rec in records:
        q=rec["record_start"]; nch=rec["nch"]
        ids=[struct.unpack_from(">h",b,q+18+6*j)[0] for j in range(nch)]
        rec["channel_ids"]=ids
        w,h=rec["width"],rec["height"]
        rgba=np.zeros((h,w,4),dtype=np.uint8)
        rgba[...,3]=255
        for j,cid in enumerate(ids):
            byte_len=struct.unpack_from(">I",b,q+18+6*j+2)[0]
            blob=b[data_cursor:data_cursor+byte_len]; data_cursor += byte_len
            if w<=0 or h<=0: continue
            ch=_decode_channel(blob,w,h)
            if cid==0: rgba[...,0]=ch
            elif cid==1: rgba[...,1]=ch
            elif cid==2: rgba[...,2]=ch
            elif cid==-1: rgba[...,3]=ch
        rec["image"]=Image.fromarray(rgba,"RGBA") if w and h else None
    return {"width":width,"height":height,"layers":records}

def parse_psd_tree(psd):
    layers=psd["layers"]
    # Canonical Photoshop layout (also used by ag-psd):
    #   type=3 hidden bounding divider -> children -> type=1/2 folder record.
    # Older research files emitted the opposite marker order, so keep a small
    # compatibility parser for those files too.
    first_div = next((r.get("divider") for r in layers if r.get("divider") is not None), None)
    canonical = (first_div == 3)
    roots=[]; stack=[]
    if canonical:
        for rec in layers:
            div=rec.get("divider")
            if div==3:
                node={"type":"group","name":rec.get("name") or "",
                      "record":rec,"children":[],"opened":True}
                (stack[-1]["children"] if stack else roots).append(node)
                stack.append(node)
            elif div in (1,2):
                if stack:
                    node=stack.pop()
                    node["name"]=rec.get("name") or node.get("name") or ""
                    node["record"]=rec
                    node["opened"]=(div==1)
                else:
                    node={"type":"group","name":rec.get("name") or "",
                          "record":rec,"children":[],"opened":(div==1)}
                    (stack[-1]["children"] if stack else roots).append(node)
            else:
                node={"type":"layer","name":rec["name"],"record":rec}
                (stack[-1]["children"] if stack else roots).append(node)
    else:
        for rec in layers:
            div=rec.get("divider")
            if div in (1,2):
                node={"type":"group","name":rec["name"],"record":rec,"children":[],"opened":(div==1)}
                (stack[-1]["children"] if stack else roots).append(node)
                stack.append(node)
            elif div==3:
                if stack: stack.pop()
            else:
                node={"type":"layer","name":rec["name"],"record":rec}
                (stack[-1]["children"] if stack else roots).append(node)
    return roots


def flatten_psd_leaf_layers(psd_path: Path):
    parsed=read_psd_layers(psd_path)
    out=[]
    for rec in parsed["layers"]:
        if rec.get("divider") is not None: continue
        if rec.get("image") is None: continue
        out.append(rec)
    return parsed,out

# ---------------- Export / recovery metadata ----------------
def build_layer_manifest(info, safe=False):
    result=[]
    for rank, r in enumerate(reversed(info["layers"])):
        x,y,w,h=r.bbox
        px=1 if safe else 0
        result.append({
            "name": layer_name(r), "animation": r.animation, "frame": r.frame,
            "part_index": r.part_index, "part_name": r.part_name,
            "fname": [r.name_index,r.fname_number], "node": [r.node_id,r.parent_id],
            "cell_id": r.cell_id, "atlas_rect": r.atlas_rect,
            "core_bbox": [x,y,w,h], "psd_bbox": [x-px,y-px,w+2*px,h+2*px],
            "safe_padding": px, "raster_quad": r.raster_quad,
            "local": r.local, "world_matrix": list(r.world_matrix),
        })
    return result


def _animation_frame_signature(animation, data, frame):
    """Stable signature for one serialized AnimationFrame expanded onto the timeline.

    SpriteStudio duration expansion repeats the same part state over consecutive
    timeline ticks. Compare the complete effective state (including parent/world
    transforms and Cell identity) so those ticks collapse to one PSD frame while
    genuinely different AnimationFrames remain separate.
    """
    states=te.make_frame_state(animation, int(frame), data["static_map"])
    worlds=te.world_matrices(states)
    signature=[]
    for pi in range(len(animation.get("parts", []))):
        st=states.get(("part",pi))
        if not st:
            signature.append((pi,None)); continue
        cell=st.get("cell")
        cell_id=getattr(cell,"cell_id",None) if cell is not None else None
        wm=worlds.get(st.get("node_id")) if st.get("node_id") is not None else None
        signature.append((
            pi, cell_id, st.get("node_id"), st.get("parent_id"), bool(st.get("hide")),
            int(st.get("prio",0)),
            tuple(round(float(st.get(k,0) or 0),7) for k in ("x","y","z","rot","sx","sy","alpha")),
            tuple(round(float(v),7) for v in wm) if wm is not None else None,
        ))
    return tuple(signature)


def unique_animation_frames(animation, data, frame_start=0, frame_end=None):
    """Return consecutive AnimationFrame runs as {frame, duration, index}.

    `frame` is the original timeline frame at which the AnimationFrame starts;
    keeping that number in PSD group names lets recovery use the exact original
    transform state without depending on a sidecar JSON file.
    """
    total=int(animation.get("frame_count") or 0)
    if frame_end is None: frame_end=total-1
    frame_start=max(0,int(frame_start)); frame_end=min(total-1,int(frame_end))
    if frame_end<frame_start: raise ValueError("Invalid frame range")
    runs=[]; last_sig=None
    for frame in range(frame_start,frame_end+1):
        sig=_animation_frame_signature(animation,data,frame)
        if not runs or sig!=last_sig:
            runs.append({"frame":frame,"duration":1,"index":len(runs)})
        else:
            runs[-1]["duration"]+=1
        last_sig=sig
    return runs


def export_animation_psd(resource, data, animation_name, outdir, texture_kind="tex", safe=False,
                          frame_start=0, frame_end=None, split_limit=MAX_PSD_LAYERS, numbered=False):
    animation=animation_by_name(data,animation_name)
    total=int(animation["frame_count"])
    if frame_end is None: frame_end=total-1
    frame_start=max(0,int(frame_start)); frame_end=min(total-1,int(frame_end))
    if frame_end<frame_start: raise ValueError("Invalid frame range")
    tex=resource.textures().get(texture_kind) or resource.tex
    if tex is None: raise FileNotFoundError(f"No {texture_kind} texture available")

    # Export one group per unique AnimationFrame, not one group per duration tick.
    af_runs=unique_animation_frames(animation,data,frame_start,frame_end)
    infos=[]
    for af in af_runs:
        _,info=render_animation_frame(resource,data,animation_name,af["frame"],texture_kind)
        info["animation_frame_index"]=af["index"]
        info["animation_frame_duration"]=af["duration"]
        infos.append(info)

    # Keep only the first occurrence of each Cell in timeline/AnimationFrame
    # order. This intentionally preserves the lowest AnimationFrame index's
    # transform when the same atlas slice is later rotated/flipped/reused.
    exported_cells=set()
    for info in infos:
        unique_layers=[]
        for r in info["layers"]:
            cid=int(r.cell_id)
            if cid in exported_cells:
                continue
            exported_cells.add(cid)
            unique_layers.append(r)
        info["layers"]=unique_layers
    base=Path(outdir); base.mkdir(parents=True,exist_ok=True)
    # Each returned info contains one frame's layer records.
    all_layers=sum((len(i["layers"])*(2 if numbered else 1)+2 for i in infos),0) + 2
    # Split automatically if needed. Numbered mode adds one independent badge
    # layer for every exported Cell, so include those records in the PSD limit.
    chunks=[]; cur=[]; cur_count=2
    for info in infos:
        add=len(info["layers"])*(2 if numbered else 1)+2
        if cur and cur_count+add>split_limit:
            chunks.append(cur);cur=[];cur_count=2
        cur.append(info);cur_count+=add
    if cur: chunks.append(cur)
    outputs=[]
    for chunk_i,chunk in enumerate(chunks,1):
        # Canonical Photoshop group encoding: bounding divider (type 3),
        # children, then the visible folder record (type 1/2).
        layers=[{"name":"</Layer group>","divider":3}]
        manifests=[]
        for info in chunk:
            frame=info["frame"]
            layers.append({"name":"</Layer group>","divider":3})
            for r in info["layers"]:
                img=r.image
                x,y,w,h=r.bbox
                if safe:
                    img=add_safe(img)
                    x-=1;y-=1
                if numbered:
                    layers.append(add_cell_number_layer(r.cell_id, x, y))
                layers.append({"name":layer_name(r),"img":img,"left":x,"top":y,"visible":True})
                m={
                    "name":layer_name(r),"animation":animation_name,"frame":frame,
                    "part_index":r.part_index,"part_name":r.part_name,
                    "fname":[r.name_index,r.fname_number],"node":[r.node_id,r.parent_id],
                    "cell_id":r.cell_id,"atlas_rect":r.atlas_rect,
                    "core_bbox":r.bbox,"psd_bbox":[x,y,img.width,img.height],
                    "safe_padding":1 if safe else 0,
                    "animation_frame_index":int(info.get("animation_frame_index",frame)),
                    "animation_frame_duration":int(info.get("animation_frame_duration",1)),
                    "local":r.local,"world_matrix":list(r.world_matrix),"raster_quad":r.raster_quad,
                }
                manifests.append(m)
            af_index=int(info.get("animation_frame_index",frame))
            layers.append({"name":f"AnimationFrame_{af_index:03d}__Frame_{frame:03d}","divider":1,
                           "divider_key":"pass","divider_subtype":0})
        layers.append({"name":animation_name,"divider":1,
                       "divider_key":"pass","divider_subtype":0})
        suffix=f"_{texture_kind}_{'numbered' if numbered else ('safe1px' if safe else 'standard')}"
        if len(chunks)>1: suffix+=f"_part{chunk_i:02d}"
        psd_path=base/f"{resource.stem}_{safe_name(animation_name)}{suffix}.psd"
        write_psd(psd_path,chunk[0]["canvas"][0],chunk[0]["canvas"][1],layers)
        manifest={"schema":"FFRS.SpritePSD.v1","version":APP_VERSION,"resource":resource.stem,
                   "texture_kind":texture_kind,"animation":animation_name,"canvas":chunk[0]["canvas"],
                   "frames":[i["frame"] for i in chunk],"safe_padding":1 if safe else 0,
                   "numbered_labels":bool(numbered),"cell_deduplication":"first occurrence in AnimationFrame order",
                   "animation_frames":[{"index":int(i.get("animation_frame_index",i["frame"])),
                                        "timeline_start":int(i["frame"]),
                                        "duration_frames":int(i.get("animation_frame_duration",1))} for i in chunk],
                   "timeline_frame_count":sum(int(i.get("animation_frame_duration",1)) for i in chunk),
                   "animation_frame_count":len(chunk),
                   "layer_count":len(manifests),"layers":manifests}
        json_path=psd_path.with_suffix(".json")
        json_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
        outputs.append((psd_path,json_path,manifest))
    return outputs



def _animation_frame_cell_sets(resource, data, animation):
    """Return frame->CellID set and one representative Part per Cell."""
    frame_sets={}; frame_occurrences={}; static_map=data["static_map"]
    for frame in range(int(animation.get("frame_count") or 0)):
        states=te.make_frame_state(animation,frame,static_map); worlds=te.world_matrices(states)
        seen=set(); occ={}
        for pi in range(len(animation.get("parts",[]))):
            st=states.get(("part",pi))
            if not st: continue
            name=st.get("part_name") or ""
            if name=="root" or name.startswith("NULL_") or st.get("hide"): continue
            c=st.get("cell"); nid=st.get("node_id")
            if c is None or nid not in worlds: continue
            if not getattr(c,"geometry_available",False) or c.width<=0 or c.height<=0: continue
            cid=int(c.cell_id); seen.add(cid); occ.setdefault(cid,pi)
        frame_sets[frame]=seen; frame_occurrences[frame]=occ
    return frame_sets,frame_occurrences


def _build_cell_usage(resource,data):
    animations=[]; all_cells=set()
    for a in data["animations"]:
        if a.get("header_type")=="Setup" or not a.get("frame_count"): continue
        fs,fo=_animation_frame_cell_sets(resource,data,a); union=set().union(*fs.values()) if fs else set()
        if not union: continue
        animations.append({"name":a["name"],"index":int(a.get("index",0)),"frame_count":int(a.get("frame_count") or 0),"frames":fs,"occurrences":fo,"cells":union})
        all_cells.update(union)
    return animations,all_cells


def _set_cover_exact(sets,universe):
    """Find a minimum-cardinality animation cover using deterministic branch-and-bound."""
    universe=set(universe)
    if not universe: return [],{"candidate_count":0,"search_nodes":0,"exact":True,"minimum_count":0}
    cells=sorted(universe); pos={c:i for i,c in enumerate(cells)}; full=(1<<len(cells))-1
    candidates=[]; seen=set()
    for item in sets:
        mask=0
        for c in item["cells"]:
            j=pos.get(c)
            if j is not None: mask|=1<<j
        if mask and mask not in seen: seen.add(mask); candidates.append((item,mask))
    reduced=[]
    for i,(item,mask) in enumerate(candidates):
        dominated=any(i!=j and mask!=m2 and (mask|m2)==m2 for j,(_,m2) in enumerate(candidates))
        if not dominated: reduced.append((item,mask))
    candidates=reduced
    cover=[[] for _ in cells]
    for k,(_,mask) in enumerate(candidates):
        mm=mask
        while mm:
            lb=mm&-mm; cover[lb.bit_length()-1].append(k); mm-=lb
    if any(not x for x in cover):
        miss=[cells[i] for i,x in enumerate(cover) if not x]; raise ValueError(f"Some Cells are not covered by any animation: {miss[:20]}")
    rem=full; greedy=[]
    while rem:
        k=max(range(len(candidates)),key=lambda j:((candidates[j][1]&rem).bit_count(),-candidates[j][0].get("index",0)))
        gain=candidates[k][1]&rem
        greedy.append(k); rem&=~gain
    best=greedy[:]; nodes=0; limit=2_000_000
    def lb(mask):
        if not mask:return 0
        mx=max((m&mask).bit_count() for _,m in candidates)
        return (mask.bit_count()+max(1,mx)-1)//max(1,mx)
    def choose(mask):
        mm=mask; best_ci=None; best_n=10**9
        while mm:
            lbv=mm&-mm; ci=lbv.bit_length()-1; n=sum(1 for k in cover[ci] if candidates[k][1]&mask)
            if n<best_n:best_n=n;best_ci=ci
            mm-=lbv
        return best_ci
    def dfs(mask,chosen,used):
        nonlocal best,nodes
        nodes+=1
        if nodes>limit:return
        if not mask:
            if len(chosen)<len(best):best=chosen[:]
            return
        if len(chosen)+lb(mask)>=len(best):return
        ci=choose(mask); choices=[k for k in cover[ci] if not (used>>k)&1]
        choices.sort(key=lambda k:(-(candidates[k][1]&mask).bit_count(),candidates[k][0].get("index",0)))
        for k in choices: dfs(mask&~candidates[k][1],chosen+[k],used|(1<<k))
    dfs(full,[],0)
    selected=[candidates[k][0] for k in best]; selected.sort(key=lambda x:(x.get("index",0),x.get("name","")))
    return selected,{"candidate_count":len(candidates),"search_nodes":nodes,"exact":nodes<=limit,"minimum_count":len(selected)}


def _choose_representative_frames(selected_anims,universe,initial_covered=None):
    """Choose representative frames greedily, optionally starting from pre-covered Cells."""
    covered=set(initial_covered or set())
    uncovered=set(universe)-covered
    chosen=[]; candidates=[]
    for a in selected_anims:
        for frame,cells in a["frames"].items():
            candidates.append((a,int(frame),set(cells)))
    while uncovered:
        valid=[x for x in candidates if x[2]&uncovered]
        if not valid:
            raise ValueError(f"Representative frames failed to cover {len(uncovered)} Cells")
        valid.sort(key=lambda x:(-len(x[2]&uncovered),x[0].get("index",0),x[1]))
        pick=valid[0]
        a,frame,cells=pick
        chosen.append({"animation":a,"frame":frame,"cells":cells})
        uncovered-=cells
        candidates=[x for x in candidates if x is not pick]
    chosen.sort(key=lambda x:(x["animation"].get("index",0),x["frame"]))
    return chosen


def _find_idle_animation(usage):
    """Find the explicit idle animation by name, case-insensitively."""
    for a in usage:
        if str(a.get("name","")).strip().lower()=="idle":
            return a
    return None


def _priority_resource_plan(usage, all_cells):
    """Build a MOD-friendly resource plan.

    When an Idle animation exists, Idle frame 0 is mandatory and acts as the
    base character sheet. Remaining Cells are then covered with the minimum
    number of non-Idle animations. Other Idle frames are used only as a final
    fallback when a Cell cannot be obtained from any other animation.
    """
    universe=set(all_cells)
    idle=_find_idle_animation(usage)
    if idle is None or 0 not in idle.get("frames",{}):
        selected,cover=_set_cover_exact(usage,universe)
        reps=_choose_representative_frames(selected,universe)
        return selected,cover,reps,{"strategy":"minimum_animation_cover","idle_anchor":None}

    idle0_cells=set(idle["frames"].get(0,set()))
    selected=[idle]
    covered=set(idle0_cells)
    uncovered=universe-covered

    other=[a for a in usage if a is not idle]
    if uncovered and other:
        try:
            extra_selected,cover=_set_cover_exact(other,uncovered)
        except ValueError:
            extra_selected=[]; cover={"candidate_count":0,"search_nodes":0,"exact":True,"minimum_count":0,"fallback":True}
        selected.extend(extra_selected)
    else:
        cover={"candidate_count":0,"search_nodes":0,"exact":True,"minimum_count":0}

    # Idle frame 0 is always first. Then choose the smallest set of frames from
    # the selected non-Idle animations to fill the uncovered Cell set.
    reps=[{"animation":idle,"frame":0,"cells":idle0_cells}]
    non_idle_selected=[a for a in selected if a is not idle]
    if non_idle_selected and uncovered:
        extra_reps=_choose_representative_frames(non_idle_selected,universe,initial_covered=covered)
        reps.extend(extra_reps)
        for x in extra_reps:
            covered.update(x["cells"])
        uncovered = universe - covered

    # If some Cells are still unique to other Idle frames, add only the needed
    # Idle frames as a last resort rather than sacrificing the preferred Idle-0
    # starting point.
    if uncovered:
        idle_candidates=[(idle,f,set(cells)) for f,cells in idle["frames"].items() if int(f)!=0 and set(cells)&uncovered]
        while uncovered and idle_candidates:
            idle_candidates.sort(key=lambda x:(-len(x[2]&uncovered),x[1]))
            a,frame,cells=idle_candidates.pop(0)
            reps.append({"animation":a,"frame":int(frame),"cells":cells})
            uncovered-=cells
        if uncovered:
            # This should only happen for malformed/incomplete animation data.
            raise ValueError(f"Resource PSD coverage failed: {len(uncovered)} Cells are not exposed by the selected animations")

    # The selected animation list is derived from the actual representative
    # frames so manifests remain truthful even when fallback Idle frames occur.
    selected_unique=[]; seen=set()
    for rf in reps:
        a=rf["animation"]
        if a.get("index") not in seen:
            seen.add(a.get("index")); selected_unique.append(a)
    return selected_unique,cover,reps,{
        "strategy":"idle_first_then_minimum_non_idle_cover",
        "idle_anchor":{"animation":idle.get("name"),"frame":0,"cell_count":len(idle0_cells)},
        "idle0_cell_count":len(idle0_cells),
        "remaining_cell_count":len(universe-idle0_cells),
    }


def _get_resource_plan(resource,data):
    """Cache coverage/set-cover/representative-frame selection for one parsed resource."""
    cache=data.setdefault("resource_plan_cache",{})
    key=str(resource.stem)
    if key not in cache:
        usage,all_cells=_build_cell_usage(resource,data)
        selected,cover,reps,strategy=_priority_resource_plan(usage,all_cells)
        cache[key]={"usage":usage,"all_cells":all_cells,"selected":selected,"cover":cover,"reps":reps,"strategy":strategy}
    return cache[key]


def export_resource_psd(resource,data,outdir,texture_kind="tex",safe=False,numbered=False):
    """Export a unique-Cell PSD using the MOD-friendly coverage strategy."""
    plan=_get_resource_plan(resource,data)
    all_cells=plan["all_cells"]; selected=plan["selected"]; cover=plan["cover"]; reps=plan["reps"]
    rendered_reps=[]; common_w=0; common_h=0
    for rf in reps:
        a=rf["animation"]; frame=rf["frame"]; _,info=render_animation_frame(resource,data,a["name"],frame,texture_kind)
        rendered_reps.append((rf,info)); common_w=max(common_w,int(info["canvas"][0])); common_h=max(common_h,int(info["canvas"][1]))

    layers=[{"name":"</Layer group>","divider":3}]; manifests=[]; exported=set()
    for rf,info in rendered_reps:
        a=rf["animation"]; frame=rf["frame"]; frame_w,frame_h=map(int,info["canvas"]); off_x=(common_w-frame_w)//2; off_y=(common_h-frame_h)//2
        layers.append({"name":"</Layer group>","divider":3})
        for r in info["layers"]:
            if int(r.cell_id) in exported: continue
            exported.add(int(r.cell_id)); img=r.image; x,y,w,h=r.bbox; x+=off_x; y+=off_y
            if safe: img=add_safe(img); x-=1; y-=1
            name=layer_name(r)
            if numbered:
                layers.append(add_cell_number_layer(r.cell_id, x, y))
            layers.append({"name":name,"img":img,"left":x,"top":y,"visible":True})
            manifests.append({"name":name,"mode":"resource","cell_id":r.cell_id,"source_animation":a["name"],"source_frame":frame,"part_index":r.part_index,"part_name":r.part_name,
                "fname":[r.name_index,r.fname_number],"node":[r.node_id,r.parent_id],"atlas_rect":r.atlas_rect,"core_bbox":r.bbox,"psd_bbox":[x,y,img.width,img.height],
                "frame_canvas":[frame_w,frame_h],"canvas_offset":[off_x,off_y],"safe_padding":1 if safe else 0,"local":r.local,"world_matrix":list(r.world_matrix),"raster_quad":r.raster_quad})
        layers.append({"name":f"{a['name']}__Frame_{frame:03d}","divider":1,"divider_key":"pass","divider_subtype":0})
    layers.append({"name":"Character Resource","divider":1,"divider_key":"pass","divider_subtype":0})
    if exported!=all_cells: raise AssertionError(f"Resource PSD omitted {len(all_cells-exported)} used Cells")
    base=Path(outdir); base.mkdir(parents=True,exist_ok=True); suffix=f"_resource_{texture_kind}_{'numbered' if numbered else ('safe1px' if safe else 'standard')}"
    psd_path=base/f"{resource.stem}{suffix}.psd"; write_psd(psd_path,common_w,common_h,layers)
    manifest={"schema":"FFRS.SpritePSD.resource.v1","version":APP_VERSION,"resource":resource.stem,"texture_kind":texture_kind,"safe_padding":1 if safe else 0,"numbered_labels":bool(numbered),"canvas":[common_w,common_h],
        "all_cell_count":len(all_cells),"exported_cell_count":len(exported),"selection_strategy":plan.get("strategy",{}),"selected_animations":[{"name":a["name"],"index":a["index"],"cell_count":len(a["cells"])} for a in selected],
        "representative_frames":[{"animation":x["animation"]["name"],"frame":x["frame"],"cell_count":len(x["cells"])} for x in reps],"cover_report":cover,"layers":manifests}
    jp=psd_path.with_suffix('.json'); jp.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    rp=base/f"{resource.stem}_resource_selection_{texture_kind}.json"; rp.write_text(json.dumps({"schema":"FFRS.SpritePSD.resource_selection.v1","version":APP_VERSION,"resource":resource.stem,"texture_kind":texture_kind,
        "all_cells":sorted(all_cells),"selection_strategy":plan.get("strategy",{}),"selected_animations":[{"name":a["name"],"index":a["index"],"cell_ids":sorted(a["cells"])} for a in selected],"representative_frames":[{"animation":x["animation"]["name"],"frame":x["frame"],"cell_ids":sorted(x["cells"])} for x in reps],"cover_report":cover},ensure_ascii=False,indent=2),encoding='utf-8')
    return [(psd_path,jp,manifest,rp)]

def safe_name(s):
    return re.sub(r"[^0-9A-Za-z_.-]+","_",str(s))


def expected_render_for_layer(info, part_index):
    for r in info["layers"]:
        if r.part_index==part_index: return r
    raise KeyError(f"Drawable Part {part_index} is not visible")

def _layer_pixel_map_from_render(r: LayerRender, data, origin):
    c_lookup=data.setdefault("cell_lookup",{})
    c=c_lookup.get(r.cell_id)
    if c is None:
        # Build once from the animation cell references.
        for a in data["animations"]:
            for p in a.get("parts",[]):
                attrs=getattr(p,"attrs",[])
                for at in attrs:
                    if at.get("name")=="Cell":
                        for k in at.get("keys",[]):
                            cell=k.get("cell")
                            if cell is not None: c_lookup[int(cell.cell_id)]=cell
    c=c_lookup.get(r.cell_id)
    if c is None: raise KeyError(f"Cell {r.cell_id} not found")
    M=source_to_screen_affine(c,r.world_matrix,origin)
    xmin,ymin,ww,hh=r.warp_bbox
    LM=M.copy(); LM[0,2]-=xmin; LM[1,2]-=ymin
    sw,sh=map(int,r.source_size)
    ids=np.arange(sw*sh,dtype=np.int32).reshape((sh,sw))
    warped=cv2.warpAffine(ids,LM.astype(np.float32),(ww,hh),flags=cv2.INTER_NEAREST,borderMode=cv2.BORDER_CONSTANT,borderValue=-1)
    bx=int(r.bbox[0]-xmin); by=int(r.bbox[1]-ymin); bw=int(r.bbox[2]); bh=int(r.bbox[3])
    return warped[by:by+bh,bx:bx+bw]

def _safe_strip(img, core_size, safe_padding):
    if safe_padding:
        if img.width < core_size[0]+2 or img.height < core_size[1]+2:
            raise ValueError("Safe PSD layer is smaller than expected 1px frame")
        return img.crop((1,1,1+core_size[0],1+core_size[1]))
    return img



def check_psd_layers(psd_path, output_dir=None, compare_psd_path=None):
    """Check PSD naming/duplicates; optionally compare edited PSD to exported reference.

    The report is deliberately issue-only: clean layers are omitted from detail arrays.
    When compare_psd_path is supplied, psd_path is the edited PSD and compare_psd_path
    is the originally exported PSD.
    """
    valid_re = re.compile(r"^Part_(\d+)__Cell_(\d+)__", re.IGNORECASE)

    def inspect(path):
        parsed, leaves = flatten_psd_leaf_layers(path)
        layers=[]; by_name=defaultdict(list); identities=defaultdict(list)
        invalid=[]
        for rec in leaves:
            name=str(rec.get("name", "")); m=valid_re.match(name)
            entry={"name":name,"bounds":[rec.get("left"),rec.get("top"),rec.get("width"),rec.get("height")]}
            if m:
                part,cell=map(int,m.groups()); pi_match=re.search(r"__part_(\d+)",name,re.IGNORECASE)
                entry.update({"part_number":part,"cell_id":cell,"part_index":int(pi_match.group(1)) if pi_match else None})
                identities[(part,cell,entry["part_index"])].append(entry)
            else:
                entry["issue"]="nonconforming_name"
                invalid.append(entry)
            by_name[name].append(entry); layers.append(entry)
        duplicates=[{"name":n,"count":len(es),"cell_ids":sorted({e.get("cell_id") for e in es if e.get("cell_id") is not None}),"layers":es} for n,es in by_name.items() if len(es)>1]
        duplicate_ids=[]
        for (part,cell,pi), es in identities.items():
            if pi is not None and len(es)>1:
                duplicate_ids.append({"part_number":part,"cell_id":cell,"part_index":pi,"count":len(es),"names":[e["name"] for e in es]})
        return parsed,layers,invalid,duplicates,duplicate_ids

    parsed,layers,invalid,duplicates,duplicate_ids=inspect(psd_path)
    issues={"nonconforming_layers":invalid,"duplicate_names":duplicates,"duplicate_tool_identities":duplicate_ids}
    comparison=None
    if compare_psd_path:
        ref_parsed,ref_layers,ref_invalid,ref_dups,ref_dupids=inspect(compare_psd_path)
        edited_by_name=defaultdict(list); ref_by_name=defaultdict(list)
        for e in layers: edited_by_name[e["name"]].append(e)
        for e in ref_layers: ref_by_name[e["name"]].append(e)
        added=[]; missing=[]
        for name, es in edited_by_name.items():
            delta=len(es)-len(ref_by_name.get(name,[]))
            if delta>0:
                added.append({"name":name,"count_added":delta,"cell_id":next((e.get("cell_id") for e in es if e.get("cell_id") is not None),None)})
        for name, es in ref_by_name.items():
            delta=len(es)-len(edited_by_name.get(name,[]))
            if delta>0:
                missing.append({"name":name,"count_missing":delta,"cell_id":next((e.get("cell_id") for e in es if e.get("cell_id") is not None),None)})
        comparison={"reference_psd":str(compare_psd_path),"edited_psd":str(psd_path),"added_layers":added,"missing_layers":missing,"added_count":sum(x["count_added"] for x in added),"missing_count":sum(x["count_missing"] for x in missing)}
        issues["comparison"]={"added_layers":added,"missing_layers":missing}
    issue_count=len(invalid)+len(duplicates)+len(duplicate_ids)
    if comparison: issue_count += comparison["added_count"]+comparison["missing_count"]
    report={"schema":"FFRS.SpritePSD.layer_check.v2","version":APP_VERSION,"source_psd":str(psd_path),"reference_psd":str(compare_psd_path) if compare_psd_path else None,"summary":{"leaf_layer_count":len(layers),"valid_tool_layer_count":sum(1 for x in layers if "cell_id" in x),"nonconforming_layer_count":len(invalid),"duplicate_exact_name_groups":len(duplicates),"duplicate_tool_identity_groups":len(duplicate_ids),"added_layer_count":comparison["added_count"] if comparison else 0,"missing_layer_count":comparison["missing_count"] if comparison else 0,"issue_count":issue_count},"issues":issues,"naming_rule":"Matches recovery parser: layer name must start with Part_<number>__Cell_<CellID>__. Only problematic layers/cells are recorded in issues."}
    outdir=Path(output_dir) if output_dir else Path(psd_path).parent
    outdir.mkdir(parents=True,exist_ok=True)
    out=outdir/(Path(psd_path).stem+("_psd_compare_report.json" if compare_psd_path else "_psd_check_report.json"))
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    return out,report

def recover_psd(psd_path, resource, data, original_kind="tex", texture_output_dir=None, original_texture_path=None):
    parsed, leaves=flatten_psd_leaf_layers(psd_path)
    root_groups=parse_psd_tree(parsed)
    animation_name=None; instances=[]; resource_mode=False
    if root_groups:
        resource_mode=any(g["type"]=="group" and g.get("name")=="Character Resource" for g in root_groups)
        animation_name=next((g["name"] for g in root_groups if g["type"]=="group" and g.get("name") and not resource_mode),None)
    if resource_mode:
        def walk_resource(node,cur_anim=None,cur_frame=None):
            if node["type"]=="group":
                name=node.get("name") or ""; m=re.fullmatch(r"(.+?)__Frame_(\d+)",name); a=cur_anim; f=cur_frame
                if m: a=m.group(1); f=int(m.group(2))
                for ch in node.get("children",[]): walk_resource(ch,a,f)
            elif cur_anim is not None and cur_frame is not None: instances.append((cur_anim,cur_frame,node["record"]))
        for g in root_groups: walk_resource(g)
        if not instances: raise ValueError("No resource PSD layers could be identified")

    # Photoshop may save a one-frame document without retaining explicit group
    # divider records (this also covers hand-made single-frame references).
    # In that case, infer animation/frame from the PSD filename against names
    # parsed from UEXP; layer order still remains irrelevant.
    if not resource_mode:
        filename_lower=Path(psd_path).stem.lower()
        if not animation_name:
            candidates=[]
            for a in data["animations"]:
                if a.get("header_type")=="Setup" or not a.get("frame_count"): continue
                marker="_"+safe_name(a["name"]).lower()+"_"
                if marker in filename_lower or filename_lower.endswith("_"+safe_name(a["name"]).lower()): candidates.append(a["name"])
            if len(candidates)==1: animation_name=candidates[0]
            elif len(candidates)>1: animation_name=max(candidates,key=len)
        if not animation_name: raise ValueError("Cannot identify animation group")
        animation=animation_by_name(data,animation_name)
        def walk(node,parent_frame=None):
            if node["type"]=="group":
                fr=parent_frame; nm=node.get("name","")
                m=re.fullmatch(r"AnimationFrame_(\d+)__Frame_(\d+)",nm)
                if m: fr=int(m.group(2))
                else:
                    m=re.fullmatch(r"Frame_(\d+)",nm)
                    if m: fr=int(m.group(1))
                for ch in node.get("children",[]): walk(ch,fr)
            elif parent_frame is not None: instances.append((animation_name,parent_frame,node["record"]))
        for g in root_groups: walk(g,None)
        if not instances:
            mm=re.search(r"_frame(\d+)(?:_|$)",filename_lower)
            if mm:
                fr=int(mm.group(1)); instances=[(animation_name,fr,r) for r in leaves if r.get("divider") is None and r.get("image") is not None]
            else: raise ValueError("No Frame_* groups could be identified in PSD")

    atlas_path=Path(original_texture_path) if original_texture_path else (resource.textures().get(original_kind) or resource.tex)
    if atlas_path is None: raise FileNotFoundError(f"Original {original_kind} texture not found")
    base=Image.open(atlas_path).convert("RGBA")
    atlas=np.array(base)

    # Recovery geometry must be evaluated against the Atlas explicitly selected
    # in the recovery UI, not the texture cache populated during preview parsing.
    # Use a detached Resource view with only the selected Atlas in the requested
    # texture slot and an isolated cache, so preview _tex pixels cannot leak into
    # PSD -> Sprite recovery (including the inverse pixel map calculations).
    recovery_textures={"tex":None,"normal":None,"mreo":None}
    recovery_textures[original_kind]=atlas_path
    recovery_resource=ssa.Resource(
        stem=resource.stem, uasset=resource.uasset, uexp=resource.uexp,
        tex=recovery_textures["tex"], normal=recovery_textures["normal"],
        mreo=recovery_textures["mreo"])
    recovery_resource._texture_cache={original_kind:{"image":base,"array":atlas}}

    proposals=defaultdict(list); diagnostics=[]; layer_re=re.compile(r"^Part_(\d+)__Cell_(\d+)__")
    frame_cache={}

    for src_anim,frame,rec in instances:
        m=layer_re.match(rec["name"])
        if not m:
            diagnostics.append({"status":"ignored","layer":rec["name"],"reason":"not a tool layer name"}); continue
        pi=int(m.group(1)); cell_id=int(m.group(2))
        if resource_mode:
            key=(src_anim,int(frame))
            if key not in frame_cache:
                try: _,frame_cache[key]=render_animation_frame(recovery_resource,data,src_anim,int(frame),original_kind)
                except Exception as exc:
                    diagnostics.append({"status":"error","layer":rec["name"],"reason":"Representative animation/frame could not be rendered","animation":src_anim,"frame":frame,"error":str(exc)}); continue
            finfo=frame_cache[key]
        else:
            if frame not in frame_cache: _,frame_cache[frame]=render_animation_frame(recovery_resource,data,animation_name,int(frame),original_kind)
            finfo=frame_cache[frame]
        try: expected=expected_render_for_layer(finfo,pi)
        except KeyError:
            diagnostics.append({"status":"error","layer":rec["name"],"reason":"Part not rendered on this frame","frame":frame,"part_index":pi}); continue
        if expected.cell_id!=cell_id:
            diagnostics.append({"status":"error","layer":rec["name"],"reason":"CellID mismatch","expected":expected.cell_id,"actual":cell_id}); continue
        x,y,w,h=expected.bbox; actual=[rec["left"],rec["top"],rec["width"],rec["height"]]
        if resource_mode:
            fw,fh=map(int,finfo["canvas"]); off=((int(parsed["width"])-fw)//2,(int(parsed["height"])-fh)//2)
            norm_actual=[actual[0]-off[0],actual[1]-off[1],actual[2],actual[3]]
        else:
            off=(0,0); norm_actual=actual
        if norm_actual==[x,y,w,h]:
            safe=0; expected_layer_origin=(x,y); expected_layer_size=(w,h)
        elif norm_actual[2:]==[w+2,h+2]:
            # Safe 1px PSD positioning policy: for an exact-size safe frame,
            # the layer raster's own top-left is the anchor. Do not reject edits
            # solely because the PSD layer origin differs from the inverse-render
            # bbox: visual edits may change content, and recovery maps the inner
            # (1,1)-(w+1,h+1) pixels through the original Cell pixel map anyway.
            # This keeps the safe frame as the spatial contract while still
            # requiring its exact expected dimensions; oversized/undersized
            # frames remain subject to stricter checks below.
            safe=1; expected_layer_origin=(norm_actual[0],norm_actual[1]); expected_layer_size=(w+2,h+2)
        elif norm_actual[:2]==[x-1,y-1] and norm_actual[2]>=w+2 and norm_actual[3]>=h+2:
            # Legacy fallback for expanded bounds when origin remains canonical.
            safe=1; expected_layer_origin=(x-1,y-1); expected_layer_size=(w+2,h+2)
        else:
            diagnostics.append({"status":"error","layer":rec["name"],"reason":"Layer origin or bounds differ from inverse coordinates","expected_core":[x,y,w,h],"expected_safe":[x-1,y-1,w+2,h+2],"actual":actual,"normalized_actual":norm_actual}); continue
        img=rec["image"].convert("RGBA")
        bounds_adjustment=None
        if img.size != expected_layer_size:
            # Anchor at the layer's original top-left and clip/pad to canonical
            # dimensions. This handles canvas growth without shifting pixels.
            normalized=Image.new("RGBA",expected_layer_size,(0,0,0,0))
            cw=min(img.width,expected_layer_size[0]); ch=min(img.height,expected_layer_size[1])
            if cw>0 and ch>0: normalized.alpha_composite(img.crop((0,0,cw,ch)),(0,0))
            bounds_adjustment={"actual_size":[img.width,img.height],"normalized_size":list(expected_layer_size),"anchor":"top-left","operation":"crop_or_pad"}
            img=normalized
        core_img=_safe_strip(img,(w,h),safe)
        local_origin=(float(finfo["canvas"][0])/2.0,float(finfo["canvas"][1])/2.0)
        ids=_layer_pixel_map_from_render(expected,data,local_origin)
        if ids.shape!=(h,w):
            diagnostics.append({"status":"error","layer":rec["name"],"reason":"Pixel map size mismatch","map_size":list(ids.shape[::-1]),"expected":[w,h]}); continue
        arr=np.asarray(core_img); seen_local={}; conflict_local=False
        for yy in range(h):
            for xx in range(w):
                sid=int(ids[yy,xx])
                if sid<0: continue
                pix=arr[yy,xx]
                prev=seen_local.get(sid)
                if prev is not None and not np.array_equal(prev,pix):
                    conflict_local=True; break
                seen_local[sid]=pix.copy()
            if conflict_local: break
        if conflict_local:
            diagnostics.append({"status":"error","layer":rec["name"],"reason":"Same source pixel maps to conflicting PSD pixels"}); continue
        for sid,pix in seen_local.items(): proposals[(expected.cell_id,sid)].append((rec["name"],pix))
        success_diag={"status":"ok","layer":rec["name"],"frame":frame,"part_index":pi,"cell_id":expected.cell_id,"safe_padding":safe,"mapped_pixels":len(seen_local)}
        if bounds_adjustment is not None: success_diag["bounds_adjustment"]=bounds_adjustment
        diagnostics.append(success_diag)

    # Build a source Cell lookup once.
    cell_lookup={}
    for a in data["animations"]:
        for p in a.get("parts",[]):
            attrs=getattr(p,"attrs",[])
            for at in attrs:
                if at.get("name")=="Cell":
                    for k in at.get("keys",[]):
                        c=k.get("cell")
                        if c is not None: cell_lookup[int(c.cell_id)]=c
    conflicts=[]; changed=0; applied=0
    for (cell_id,sid),vals in proposals.items():
        c=cell_lookup.get(cell_id)
        if c is None or c.width<=0: continue
        uniq={bytes(v.tobytes()):v for _,v in vals}
        sx=int(c.x)+(sid%int(c.width)); sy=int(c.y)+(sid//int(c.width))
        if sx<0 or sy<0 or sx>=atlas.shape[1] or sy>=atlas.shape[0]: continue
        orig=atlas[sy,sx].copy()
        modified={k:v for k,v in uniq.items() if not np.array_equal(v,orig)}
        if not modified:
            continue
        if len(modified)>1:
            conflicts.append({"cell_id":cell_id,"source_pixel":sid,"layers":[n for n,v in vals if not np.array_equal(v,orig)],"variants":len(modified)}); continue
        new=next(iter(modified.values())); atlas[sy,sx]=new; changed+=1; applied+=1

    outdir=Path(texture_output_dir or psd_path.parent); outdir.mkdir(parents=True,exist_ok=True)
    out=outdir/(Path(original_kind).stem+"_recovered.png"); Image.fromarray(atlas,"RGBA").save(out)

    # Extra diagnostic output: retain the normal recovered sprite unchanged,
    # and create a second copy annotated with each real Cell ID at its atlas
    # rectangle's top-left corner. The labels are burned into this diagnostic
    # copy only; they are never fed back into PSD recovery.
    numbered = Image.fromarray(atlas.copy(), "RGBA")
    ndraw = ImageDraw.Draw(numbered)
    numbered_cell_ids = set()
    for anim in data.get("animations", []):
        for part in anim.get("parts", []):
            for attr in getattr(part, "attrs", []):
                if attr.get("name") != "Cell":
                    continue
                for key in attr.get("keys", []):
                    cell = key.get("cell")
                    if cell is None:
                        continue
                    cid = int(cell.cell_id)
                    if cid in numbered_cell_ids or int(cell.width) <= 0 or int(cell.height) <= 0:
                        continue
                    numbered_cell_ids.add(cid)
                    x, y = int(cell.x), int(cell.y)
                    if x < 0 or y < 0 or x >= numbered.width or y >= numbered.height:
                        continue
                    badge = add_cell_number_layer(cid, x, y)["img"]
                    # Keep the badge fully inside the canvas where possible.
                    bx = min(max(0, x), max(0, numbered.width - badge.width))
                    by = min(max(0, y), max(0, numbered.height - badge.height))
                    numbered.alpha_composite(badge, (bx, by))
    numbered_out = outdir/(Path(original_kind).stem+"_recovered_numbered.png")
    numbered.save(numbered_out)

    report=out.with_name(out.stem+"_recovery_report.json")
    # Error-only report: successful layers, ignored layers, totals and normal
    # processing metadata are intentionally omitted to keep the report actionable.
    error_items=[]
    reason_explanations={
        "Part not rendered on this frame":"当前帧的逆向渲染结果中不存在该 Part，无法建立像素映射。常见原因：PSD 层来自其他帧/旧版本，或该 Part 在当前帧未激活、被隐藏，或层名中的 Part/Cell 身份与当前帧不匹配。此错误不是像素锚点偏移。",
        "CellID mismatch":"PSD 层名中的 Cell 编号与该动画帧实际引用的 Cell 不一致。请检查是否改过层名、复制错层，或 PSD 与当前 .uexp 并非同一版本。",
        "Layer origin or bounds differ from inverse coordinates":"PSD 图层左上锚点或尺寸与逆向坐标计算结果不符。可能是像素锚点偏移、画布/图层被移动、裁切尺寸改变，或 Safe 1px 边界不符合预期。",
        "Pixel map size mismatch":"逆向像素映射矩阵的尺寸与 Cell 的预期宽高不一致，无法可靠地将 PSD 像素写回源 Atlas。请检查 Cell 几何数据、锚点和安全边界。",
        "Same source pixel maps to conflicting PSD pixels":"多个 PSD 像素映射到同一个源 Atlas 像素，但颜色/透明度不同，存在写回冲突。请检查重叠图层或同一 Cell 的重复副本是否被修改成不同内容。",
        "Representative animation/frame could not be rendered":"无法重建该 PSD 层对应的动画帧，因此无法验证 Cell 身份和像素锚点。请检查动画名称、帧号及原始 .uasset/.uexp 是否匹配。"
    }
    for item in diagnostics:
        if item.get("status") != "error":
            continue
        err=dict(item)
        err["cause_zh"]=reason_explanations.get(item.get("reason"),"恢复过程无法验证该层与源 Cell 的对应关系；请检查层身份、动画帧、逆向坐标及像素边界。")
        error_items.append(err)
    for item in conflicts:
        err={"status":"error","reason":"同一源像素存在冲突写回","cell_id":item.get("cell_id"),"details":item}
        err["cause_zh"]="同一源 Cell 像素收到多个不一致的 PSD 像素值；通常由共享 Cell 的多个图层被分别修改且内容不一致导致。"
        error_items.append(err)
    report.write_text(json.dumps({"schema":"FFRS.SpritePSD.recovery-errors.v1","errors":error_items},ensure_ascii=False,indent=2),encoding="utf-8")
    return out,report,conflicts

def save_analysis_cache(resource, data, outdir):
    # Reuse the established CSV cache format so the old Analyzer and this tool
    # can share the same analysis output.
    outdir=Path(outdir); outdir.mkdir(parents=True,exist_ok=True)
    names=data["names"]; animations=data["animations"]
    cells,records=ssa.parse_cell_defs(resource.uexp,names)
    refs=ssa.parse_cell_refs(resource.uexp)
    tracks=ssa.resolve_tracks(animations,refs,cells,records)
    atlas_for_origin=resource.tex or resource.normal or resource.mreo
    if atlas_for_origin and atlas_for_origin.exists():
        try:
            im=Image.open(atlas_for_origin).convert("RGBA")
            origin=ssa.make_atlas_origin_cell(im,cells)
            if origin and not any(c.geometry_available and c.cell_id==0 for c in cells):
                cells.insert(0,origin)
        except Exception: pass
    with (outdir/"ss6_cellmap.csv").open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.writer(f); w.writerow(["cell_id","cell_name","cell_ref_name","cellmap_name","cell_index","x","y","width","height","pivot_x","pivot_y","record_type","geometry_available","record_offset_hex","texture_png"])
        for c in cells: w.writerow([c.cell_id,c.name,ssa.cell_ref_name(c),c.name,c.sub_index,c.x,c.y,c.width,c.height,c.pivot_x,c.pivot_y,c.record_type,c.geometry_available,hex(c.record_offset),str(resource.tex or atlas_for_origin) if atlas_for_origin else ""])
    return tracks,cells
