#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SpriteSliceAnalyzer v1.0

FFRS / Unreal Engine 5.6 cooked SpriteStudio resource analyzer.

Animation model:
    Animation -> Part -> Cell Key -> Cell Reference -> Cell Definition -> XYWH

The tool does not use JSON/sidecar data as animation evidence.
"""
from __future__ import annotations
import csv, json, math, os, re, struct, traceback
from dataclasses import dataclass, asdict
from pathlib import Path
from collections import defaultdict
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
try:
    from PIL import Image, ImageDraw, ImageFont, ImageTk
except ImportError:
    Image = ImageDraw = ImageFont = ImageTk = None

APP_VERSION = "1.0"

MAGIC_ANIM = bytes.fromhex("80 0D 22")
MAGIC_SETUP = bytes.fromhex("80 0D 02")
MAGIC_CELL_DEF = bytes.fromhex("80 1D 70 30")
MAGIC_CELL_REF = bytes.fromhex("80 09 0E 01")
MAGIC_CELL_KEY = bytes.fromhex("80 05 01")
KEY_MARKER = bytes.fromhex("80 0F 7F")
ATTR_NAMES = {1:"Posx",2:"Posy",6:"Rotz",7:"Sclx",8:"Scly",13:"Prio",16:"Hide",35:"Unknown_35"}
ATTR_NAMES = {1:"Posx",2:"Posy",6:"Rotz",7:"Sclx",8:"Scly",13:"Prio",16:"Hide",35:"Unknown_35"}
@dataclass
class Cell:
    cell_id:int
    record_offset:int
    name_index:int
    sub_index:int
    name:str
    x:int
    y:int
    width:int
    height:int
    pivot_x:float
    pivot_y:float
    record_type:str = "70"
    geometry_available:bool = True

@dataclass
class CellReference:
    order:int
    offset:int
    name:str
    length:int

@dataclass
class CellKey:
    animation:str
    animation_index:int
    part:str
    part_index:int
    key_index:int
    frame:int
    reference:str
    reference_order:int
    cell_id:int|None
    record_offset:int|None

@dataclass
class Track:
    track_id:int
    animation:str
    animation_index:int
    part:str
    part_index:int
    frame_count:int
    end_frame:int
    fps:int
    keys:list

@dataclass
class Resource:
    stem:str
    uasset:Path
    uexp:Path
    tex:Path|None
    normal:Path|None
    mreo:Path|None

    @property
    def png(self):
        # Backward-compatible alias: the preview always uses _tex.
        return self.tex

    def textures(self):
        return {
            'tex': self.tex,
            'normal': self.normal,
            'mreo': self.mreo,
        }


def decode_fname_number(name, number):
    # In this cooked asset the serialized FName Number is one greater than the
    # human-facing suffix: 0 = no suffix, 2 = _1, 3 = _2.
    return name if number == 0 else f"{name}_{number-1}"


def read_name_table(uasset:Path):
    """Recover the serialized FName string table from a cooked UE5 uasset.

    The older implementation assumed the first FString record always started
    at 0x113. That is true for the original unit0010/unit0020 assets, but not
    for every cooked character asset (pc0010 starts at 0x115). The table is
    still the same FString-like sequence; only its start offset can move.

    We therefore scan the small header/name region for a candidate sequence,
    validate the whole sequence, and prefer the candidate containing the
    standard Engine/Texture2D tail. This is only FName-table recovery; no JSON
    data is consulted.
    """
    b=uasset.read_bytes()
    candidates=[]
    # In these cooked assets the name table begins shortly after the compact
    # package header. Keep the scan bounded so arbitrary payload bytes later in
    # the file cannot be mistaken for a name table.
    scan_end=min(len(b)-4,0x400)
    for start in range(0x100,scan_end):
        p=start; out=[]
        while p+4<=len(b):
            n=struct.unpack_from('<i',b,p)[0]
            if n<=0 or n>4096 or p+4+n+4>len(b):
                break
            raw=b[p+4:p+4+n]
            if not raw or raw[-1] != 0:
                break
            try:
                text=raw[:-1].decode('utf-8')
            except UnicodeDecodeError:
                break
            if not text or any(ord(c)<32 for c in text):
                break
            out.append(text)
            p+=4+n+4
        if len(out)>=8:
            score=0
            if '/Script/Engine' in out: score+=1000
            if 'Texture2D' in out: score+=500
            if any(x.endswith('_tex') for x in out): score+=200
            score+=min(len(out),500)
            candidates.append((score,start,out))
    if not candidates:
        raise ValueError("UE5 FName table could not be recovered from uasset")
    candidates.sort(key=lambda x:(x[0],len(x[2])),reverse=True)
    return candidates[0][2]


def parse_cell_defs(uexp:Path,names):
    """Parse CellMap records found in FFRS UEXP.

    70 = the normal Cell record with full XYWH + pivot.
    78 = a second full-rectangle variant; it still carries usable XYWH.
    72/7C/74 = special Cell-like records referenced by animation Cell keys,
    but their serialized payload does not contain a normal XYWH rectangle.
    They are retained for reference resolution, but are never guessed into a
    crop rectangle.
    """
    b=uexp.read_bytes(); out=[]; records={}; p=0
    variants={'70':53,'72':45,'78':45,'7c':37,'74':None}
    while True:
        p=b.find(b"\x80\x1d",p)
        if p<0 or p+12>len(b): break
        typ=b[p+2:p+3].hex()
        if b[p+3:p+4]!=b"\x30" or typ not in variants:
            p+=1; continue
        ni,si=struct.unpack_from('<II',b,p+4)
        if not (0<=ni<len(names)):
            p+=1; continue
        name=names[ni]
        refname=decode_fname_number(name,si)
        # All known variants contain x/y immediately after the two FName fields.
        try:
            x,y=struct.unpack_from('<2f',b,p+12)
        except struct.error:
            p+=1; continue
        if not all(math.isfinite(v) for v in (x,y)):
            p+=1; continue
        valid_tail=False
        if typ in ('70','72','78'):
            # The standard variants have a final byte 03 at their fixed length.
            L=variants[typ]
            valid_tail=(p+L<=len(b) and b[p+L-1]==3)
        elif typ=='7c':
            valid_tail=(p+37<=len(b) and b[p+36]==3)
        else: # 74: variable special record; accept the structurally valid header.
            valid_tail=True
        if not valid_tail:
            p+=1; continue
        if typ in ('70','78'):
            vals=struct.unpack_from('<6f',b,p+12)
            if not all(math.isfinite(v) for v in vals):
                p+=1; continue
            xx,yy,w,h,px,py=vals
            if not (0<=w<=8192 and 0<=h<=8192):
                p+=1; continue
            rec=Cell(len(out)+1,p,ni,si,name,int(round(xx)),int(round(yy)),
                     int(round(w)),int(round(h)),px,py,typ,True)
            out.append(rec)
        elif typ=='72':
            # x/y + two floats used by the special record; width/height are
            # not serialized here, so they must remain unavailable.
            px,py=struct.unpack_from('<2f',b,p+20)
            rec=Cell(0,p,ni,si,name,int(round(x)),int(round(y)),0,0,px,py,typ,False)
        elif typ=='7c':
            rec=Cell(0,p,ni,si,name,int(round(x)),int(round(y)),0,0,0.0,0.0,typ,False)
        else: # 74
            rec=Cell(0,p,ni,si,name,int(round(x)),int(round(y)),0,0,0.0,0.0,typ,False)
        records[refname]=rec
        p += 4
    return out, records


def cell_ref_name(cell:Cell):
    return cell.name if cell.sub_index==0 else f"{cell.name}_{cell.sub_index-1}"


def parse_cell_refs(uexp:Path):
    b=uexp.read_bytes(); out=[]; p=0
    while True:
        p=b.find(MAGIC_CELL_REF,p)
        if p<0 or p+8>len(b): break
        n=struct.unpack_from('<I',b,p+4)[0]
        if 1<=n<=256 and p+8+n<=len(b):
            raw=b[p+8:p+8+n].rstrip(b'\0')
            clean=raw.rstrip(b'\r\n\t ')
            if clean and all(32<=c<127 for c in clean):
                raw=clean
                out.append(CellReference(len(out),p,raw.decode('utf-8'),n))
                p+=8+n; continue
        p+=1
    return out


def parse_key(b,q,end):
    start=q
    if b[q:q+3]==bytes.fromhex('80 09 03'):
        ip='None'; frame=0; head=3
    elif b[q:q+3]==bytes.fromhex('80 09 02') and q+7<=end:
        ip='None'; frame=struct.unpack_from('<I',b,q+3)[0]; head=7
    elif b[q:q+4]==bytes.fromhex('80 09 01 01'):
        ip='Linear'; frame=0; head=4
    elif b[q:q+4]==bytes.fromhex('80 09 01 03'):
        ip='Curve'; frame=0; head=4
    elif b[q:q+7]==bytes.fromhex('00 09 00 00 00 00 01') or (b[q:q+2]==b'\x00\x09' and q+7<=end and b[q+3:q+7]==b'\x00\x00\x00\x01'):
        ip='Linear'; frame=b[q+2]; head=7
    elif b[q:q+2]==b'\x00\x09' and q+7<=end and b[q+3:q+7]==b'\x00\x00\x00\x03':
        ip='Curve'; frame=b[q+2]; head=7
    else:
        raise ValueError(f"Unknown key header at 0x{q:X}: {b[q:q+16].hex(' ')}")
    if ip=='Curve':
        marker=b[q+head:q+head+3]
        if marker not in (bytes.fromhex('80 0f 78'), bytes.fromhex('80 0f 70')):
            raise ValueError(f"Missing curve marker at 0x{q:X}")
    elif b[q+head:q+head+3] != KEY_MARKER:
        raise ValueError(f"Missing key marker at 0x{q:X}")
    v=q+head+3
    if ip=='Curve':
        marker=b[q+head:q+head+3]
        if marker==bytes.fromhex('80 0f 78'):
            # FFRS curve key: 3 float32 parameters followed by an embedded
            # uint value record (9 bytes).
            if v+21>end or b[v+12:v+16]!=bytes.fromhex('80 09 04 03'):
                raise ValueError(f"Truncated/invalid curve key at 0x{q:X}")
            value_type='curve'; value=struct.unpack_from('<3f',b,v); size=21
        else:
            # Alternate curve marker stores 4 float32 parameters, followed
            # by the same embedded uint value record.
            if v+25>end or b[v+16:v+20]!=bytes.fromhex('80 09 04 03'):
                raise ValueError(f"Truncated/invalid curve key at 0x{q:X}")
            value_type='curve'; value=struct.unpack_from('<4f',b,v); size=25
    elif b[v:v+4]==bytes.fromhex('80 09 0E 03'):
        value_type='zero'; value=0; size=4
    elif b[v:v+4]==bytes.fromhex('80 09 0E 05'):
        value_type='cell_ref'; value=None; size=4
    elif b[v:v+4]==bytes.fromhex('80 09 0C 03') and v+8<=end:
        value_type='int'; value=struct.unpack_from('<i',b,v+4)[0]; size=8
    elif b[v:v+4]==bytes.fromhex('80 09 04 03') and v+9<=end:
        value_type='uint'; value=struct.unpack_from('<I',b,v+4)[0]; size=9
    else:
        raise ValueError(f"Unknown key value at 0x{v:X}: {b[v:v+16].hex(' ')}")
    return {'offset':start,'frame':frame,'iptype':ip,'value_type':value_type,
            'value':value,'end':v+size}


def parse_attribute(b,q,end):
    if b[q:q+3]==MAGIC_CELL_KEY:
        count=struct.unpack_from('<I',b,q+3)[0]; name='Cell'; head=7
    elif b[q:q+2]==b'\x00\x05' and q+7<=end:
        code=b[q+2]; count=struct.unpack_from('<I',b,q+3)[0]
        if not 1<=count<=512: raise ValueError(f"Invalid key count {count} at 0x{q:X}")
        if code not in ATTR_NAMES:
            # Unknown/non-Cell attributes are still part of the Part stream.
            # Their values may use additional nested codecs that are irrelevant
            # to Cell playback. Use the serialized key-marker count to advance
            # without assigning an unverified semantic meaning.
            p=q+7
            for _ in range(count):
                m=b.find(KEY_MARKER,p,end)
                if m<0: raise ValueError(f"Cannot locate key marker for unknown attribute {code} at 0x{q:X}")
                p=m+3
            # The next 00 05 block is either the next attribute or the next
            # Part. Cell attributes use 80 05 01, so include that as well.
            candidates=[x for x in (b.find(b'\x00\x05',p,end), b.find(MAGIC_CELL_KEY,p,end)) if x>=0]
            nq=min(candidates) if candidates else end
            return {'name':f'Unknown_{code}','count':count,'keys':[{'offset':0,'frame':0,'iptype':'Unknown','value_type':'unknown','value':None,'end':0} for _ in range(count)],'start':q,'end':nq},nq
        name=ATTR_NAMES[code]; head=7
    else:
        raise ValueError(f"Unknown attribute header at 0x{q:X}: {b[q:q+16].hex(' ')}")
    if not 1<=count<=512: raise ValueError(f"Invalid key count {count} at 0x{q:X}")
    start=q; q+=head; keys=[]
    for _ in range(count):
        k=parse_key(b,q,end); keys.append(k); q=k['end']
    return {'name':name,'count':count,'keys':keys,'start':start,'end':q},q


def parse_part(b,q,end,names):
    if b[q:q+2]!=b'\x00\x05': raise ValueError(f"Invalid Part header at 0x{q:X}")
    ni=struct.unpack_from('<I',b,q+2)[0]
    attr_count=struct.unpack_from('<I',b,q+10)[0]
    if not 0<=ni<len(names) or not 1<=attr_count<=64:
        raise ValueError(f"Invalid Part header at 0x{q:X}")
    q0=q+14; attrs=[]
    for _ in range(attr_count):
        a,q0=parse_attribute(b,q0,end); attrs.append(a)
    return {'name':names[ni],'name_index':ni,'attrs':attrs,'start':q,'end':q0},q0


def parse_animations(uasset:Path,uexp:Path):
    names=read_name_table(uasset); b=uexp.read_bytes()
    headers=[]
    for magic in (MAGIC_ANIM,MAGIC_SETUP):
        p=0
        while True:
            x=b.find(magic,p)
            if x<0: break
            headers.append(x); p=x+1
    headers=sorted(set(headers)); next_header={x:(headers[i+1] if i+1<len(headers) else len(b)) for i,x in enumerate(headers)}
    animations=[]; parts_total=0; cell_keys=[]
    for ai,off in enumerate(headers):
        magic=b[off:off+3]
        ni,num=struct.unpack_from('<II',b,off+3)
        if ni>=len(names): raise ValueError(f"Animation FName index {ni} is outside name table")
        name=decode_fname_number(names[ni],num)
        settings=b[off+11:off+15]
        frame_count=struct.unpack_from('<I',b,off+18)[0]
        canvas_x,canvas_y=struct.unpack_from('<2f',b,off+22)
        end_frame=struct.unpack_from('<I',b,off+30)[0]
        is_normal=(magic==MAGIC_ANIM and settings[:3]==bytes.fromhex('80 0F 34'))
        is_pose=(magic==MAGIC_ANIM and settings[:3]==bytes.fromhex('80 0F 74'))
        is_setup=(magic==MAGIC_SETUP)
        if is_normal or (magic==MAGIC_ANIM and settings[:3] in (bytes.fromhex('80 0f 30'), bytes.fromhex('80 0f 10'))):
            pc0=struct.unpack_from('<I',b,off+34)[0]
            pc1=struct.unpack_from('<I',b,off+35)[0] if off+39<=len(b) else 0
            # Some FFRS categories insert one byte before Canvas/EndFrame/
            # PartCount. The shifted layout is identifiable by a plausible
            # PartCount at +35 and a valid Part header at +39.
            shifted=((not (1<=pc0<=64 and b[off+38:off+40]==b'\x00\x05')) and 1<=pc1<=512)
            if shifted:
                # Shifted header variants:
                #   A: PartCount at +35, first Part at +39
                #   B: an extra 4-byte field exists; PartCount at +39,
                #      first Part at +43.
                cand1=off+39
                cand2=off+43
                valid1=False; valid2=False
                for qq in (cand1,cand2):
                    if qq+14<=next_header[off] and b[qq:qq+2]==b'\x00\x05':
                        ni0=struct.unpack_from('<I',b,qq+2)[0]
                        ac0=struct.unpack_from('<I',b,qq+10)[0]
                        if 0<=ni0<len(names) and 1<=ac0<=64:
                            if qq==cand1: valid1=True
                            else: valid2=True
                if valid1:
                    part_count=pc1; q=cand1
                elif valid2:
                    part_count=struct.unpack_from('<I',b,off+39)[0]; q=cand2
                else:
                    raise ValueError(f"Cannot locate first Part for animation at 0x{off:X}")
                frame_count=struct.unpack_from('<I',b,off+18)[0]
                canvas_x,canvas_y=struct.unpack_from('<2f',b,off+23)
                end_frame=struct.unpack_from('<I',b,off+31)[0]
            else:
                part_count=pc0; q=off+38
        elif is_pose or is_setup:
            part_count=None
            q=off+34
            # Setup variants may carry 6/7 bytes of padding before the first Part.
            # Locate the first structurally valid Part header inside that small prefix.
            found=None
            for qq in range(q,min(q+16,next_header[off])):
                if b[qq:qq+2]==b'\x00\x05' and qq+14<=next_header[off]:
                    ni0=struct.unpack_from('<I',b,qq+2)[0]
                    ac0=struct.unpack_from('<I',b,qq+10)[0]
                    if 0<=ni0<len(names) and 1<=ac0<=64:
                        found=qq; break
            if found is not None: q=found
            else:
                # Empty Setup section.
                q=next_header[off]
        else:
            raise ValueError(f"Unknown animation header at 0x{off:X}: {settings.hex(' ')}")
        parts=[]
        while q<next_header[off]:
            if part_count is not None and len(parts)>=part_count: break
            # Pose/Setup sections end with a short zero terminator.
            if part_count is None:
                # Setup/Pose sections may have variable padding before their
                # first Part. Once a structurally valid Part header is found,
                # parse it; if none exists, this section is empty.
                if b[q:q+4]==b'\x00\x00\x00\x00':
                    found=None
                    for qq in range(q,min(q+24,next_header[off])):
                        if b[qq:qq+2]==b'\x00\x05' and qq+14<=next_header[off]:
                            ni0=struct.unpack_from('<I',b,qq+2)[0]
                            ac0=struct.unpack_from('<I',b,qq+10)[0]
                            if 0<=ni0<len(names) and 1<=ac0<=64:
                                found=qq; break
                    if found is None: break
                    q=found
            part,q=parse_part(b,q,next_header[off],names); parts.append(part)
        if part_count is not None and len(parts)!=part_count:
            raise ValueError(f"Animation {name}: expected {part_count} Parts, parsed {len(parts)}")
        for pi,part in enumerate(parts):
            for attr in part['attrs']:
                if attr['name']!='Cell': continue
                for ki,key in enumerate(attr['keys']):
                    cell_keys.append((ai,name,pi,part['name'],ki,key))
        parts_total+=len(parts)
        fps=30 if settings[-1]==0x1e else 60
        animations.append({'index':ai,'name':name,'name_index':ni,'fname_number':num,
                           'offset':off,'header_type':'Setup' if is_setup else ('Pose' if is_pose else 'Normal'),
                           'settings':settings.hex(' '),'frame_count':frame_count,'end_frame':end_frame,
                           'canvas_x':canvas_x,'canvas_y':canvas_y,'fps':fps,'part_count':len(parts),'parts':parts})
    return names,animations,parts_total,cell_keys


def resolve_tracks(animations, cell_refs, cells, cell_records=None):
    # Reference strings are serialized in one stream. Most are Cell references,
    # but some FFRS character assets also contain event/reference tracks (for
    # example the footstep and rope tracks). Consume every reference-bearing
    # key in animation order, while only emitting Cell tracks.
    ref_keys=[]
    for a in animations:
        for p in a['parts']:
            for at in p['attrs']:
                if at['name'] not in ('Cell','Unknown_35'): continue
                for ki,k in enumerate(at['keys']):
                    ref_keys.append((at['name'],a,p,ki,k))
    ref_offset=0
    if len(cell_refs) != len(ref_keys):
        delta=len(cell_refs)-len(ref_keys)
        # Some assets serialize one or more Setup/static Cell references before
        # the animation reference stream. When a Setup header is present and
        # there are extra leading references, keep those references unassigned
        # and align the animation keys to the remaining stream.
        if delta>0 and any(a.get('header_type')=='Setup' for a in animations):
            ref_offset=delta
        else:
            raise ValueError(f"Reference key count ({len(ref_keys)}) does not match serialized reference count ({len(cell_refs)}); refusing to guess alignment.")
    ref_by_name=defaultdict(list)
    for c in cells: ref_by_name[cell_ref_name(c)].append(c)
    tracks=[]; ref_i=0; tid=1
    cell_lookup={}
    for c in cells: cell_lookup[cell_ref_name(c)]=c
    if cell_records:
        cell_lookup.update(cell_records)
    for a in animations:
        for pi,p in enumerate(a['parts']):
            for attr in p['attrs']:
                if attr['name'] not in ('Cell','Unknown_35'): continue
                keys=[]
                for ki,k in enumerate(attr['keys']):
                    r=cell_refs[ref_i+ref_offset]; ref_i+=1
                    if attr['name']=='Unknown_35':
                        continue
                    c=cell_lookup.get(r.name)
                    ck={'animation':a['name'],'animation_index':a['index'],'part':p['name'],'part_index':pi,
                        'key_index':ki,'frame':k['frame'],'iptype':k['iptype'],'reference':r.name,
                        'reference_order':r.order,'reference_offset':r.offset,'cell_id':c.cell_id if c else None,
                        'x':c.x if c else None,'y':c.y if c else None,'width':c.width if c else None,
                        'height':c.height if c else None,'pivot_x':c.pivot_x if c else None,'pivot_y':c.pivot_y if c else None,
                        'record_offset':c.record_offset if c else None,
                        'record_type':c.record_type if c else None, 'geometry_available':c.geometry_available if c else False}
                    keys.append(ck)
                    cell_lookup_key=(a['index'],pi,ki); cell_lookup[cell_lookup_key]=ck
                tracks.append(Track(tid,a['name'],a['index'],p['name'],pi,a['frame_count'],a['end_frame'],a['fps'],keys));tid+=1
    return tracks


def resource_for(uasset:Path):
    stem=uasset.stem; uexp=uasset.with_suffix('.uexp')
    if not uexp.exists(): return None

    # FFRS character resources share one UAsset/UEXP between three texture
    # variants.  Any one of them is enough to make the resource selectable.
    tex_cands=[uasset.with_name(stem+'_tex.png'),uasset.with_name(stem+'.png'),uasset.with_name(stem+'_tex(1).png')]
    tex=next((p for p in tex_cands if p.exists()),None)
    normal=uasset.with_name(stem+'_normal.png')
    mreo=uasset.with_name(stem+'_mreo.png')
    if not normal.exists(): normal=None
    if not mreo.exists(): mreo=None
    if tex is None and normal is None and mreo is None:
        return None
    return Resource(stem,uasset,uexp,tex,normal,mreo)


def preferred_texture(res:Resource):
    """Return the texture used for geometry-only visual checks.

    _tex is preferred because it is the only texture shown in the preview.
    If _tex is absent, another supplied variant can still provide the same
    atlas dimensions for Cell #0 detection and crop generation.
    """
    return res.tex or res.normal or res.mreo


def texture_crop_dir(outdir:Path,kind:str):
    return outdir/'crops' if kind=='tex' else outdir/f'crops_{kind}'


def texture_numbered_dir(outdir:Path,kind:str):
    return outdir/'crops_numbered' if kind=='tex' else outdir/f'crops_numbered_{kind}'


def export_texture_crops(res:Resource,outdir:Path,cells,export_crops=True,only_missing=False):
    """Export the same Cell rectangles from every available texture variant.

    The UEXP/CellMap is parsed exactly once. _tex/_normal/_mreo only differ in
    pixel data, so all three use the same XYWH records and filenames.
    """
    if not export_crops or Image is None:
        return
    for kind,path in res.textures().items():
        if not path or not path.exists():
            continue
        im=Image.open(path).convert('RGBA')
        clean=texture_crop_dir(outdir,kind); numbered=texture_numbered_dir(outdir,kind)
        clean.mkdir(exist_ok=True); numbered.mkdir(exist_ok=True)
        for c in cells:
            cr=crop_image(im,c)
            if cr.width>1 and cr.height>1:
                fn=f'{c.cell_id:04d}_{safe_name(c.name)}_{c.sub_index}.png'
                if only_missing and (clean/fn).exists() and (numbered/fn).exists():
                    continue
                if not (only_missing and (clean/fn).exists()):
                    cr.save(clean/fn)
                if not (only_missing and (numbered/fn).exists()):
                    annotate_crop(cr,c.cell_id).save(numbered/fn)


def discover_resources(root:Path,sub='char'):
    d=root/sub; d.mkdir(parents=True,exist_ok=True); out=[]
    for p in sorted(d.glob('*.uasset')):
        r=resource_for(p)
        if r: out.append(r)
    return out


def safe_name(s): return re.sub(r'[^0-9A-Za-z_.-]+','_',s)


def crop_image(im,c):
    x,y,w,h=c.x,c.y,c.width,c.height
    x0=max(0,x);y0=max(0,y);x1=min(im.width,x+w);y1=min(im.height,y+h)
    if x1<=x0 or y1<=y0: return Image.new('RGBA',(1,1),(0,0,0,0))
    return im.crop((x0,y0,x1,y1))


def annotate_crop(im,number):
    out=im.convert('RGBA').copy(); d=ImageDraw.Draw(out)
    try: font=ImageFont.truetype('arial.ttf',max(10,min(28,out.height//3)))
    except Exception: font=ImageFont.load_default()
    text=str(number); bb=d.textbbox((0,0),text,font=font); tw=bb[2]-bb[0];th=bb[3]-bb[1]
    pad=max(2,min(8,out.width//12 if out.width else 2))
    d.rectangle((0,0,min(out.width,tw+pad*2),min(out.height,th+pad*2)),fill=(0,0,0,190))
    d.text((pad,pad),text,fill=(255,255,0,255),font=font)
    return out


def make_atlas_origin_cell(im, cells):
    """Create synthetic Cell #0 for an unreferenced sprite at atlas (0,0).

    Some FFRS atlases contain a valid sprite in the very top-left packed
    region even though that region has no Cell definition/reference in the
    UEXP. It is not an animation key, so it is exported as Cell #0 only and
    is never added to animation playback tracks.
    """
    if im is None or not cells or any(c.geometry_available and c.cell_id == 0 for c in cells):
        return None
    full=[c for c in cells if c.geometry_available and c.width > 1 and c.height > 1 and c.x >= 0 and c.y >= 0]
    if not full or any(c.x == 0 and c.y == 0 for c in full):
        return None

    # Prefer boundaries from parsed Cells touching the top/left atlas edges.
    xs=[c.x for c in full if c.y == 0 and c.x > 0]
    ys=[c.y for c in full if c.x == 0 and c.y > 0]
    if not xs:
        xs=[v for c in full for v in (c.x, c.x+c.width) if v > 0]
    if not ys:
        ys=[v for c in full for v in (c.y, c.y+c.height) if v > 0]
    if not xs or not ys:
        return None
    w=min(xs); h=min(ys)
    if w <= 1 or h <= 1 or w > im.width or h > im.height:
        return None

    # Require visible pixels so an empty transparent margin is not exported.
    if 'A' not in im.getbands():
        return None
    if im.crop((0,0,w,h)).getchannel('A').getbbox() is None:
        return None
    return Cell(0,-1,0,0,'AtlasOrigin',0,0,w,h,0.0,0.0,'origin',True)


def load_saved_analysis(res:Resource,outdir:Path):
    """Load a previously exported analysis from CSV files.

    This is a cache/reuse path only. It never uses JSON as parsing evidence.
    The persisted CSV tables are the same tables produced by save_analysis().
    """
    required=[outdir/'ss6_cellmap.csv',outdir/'cell_references.csv',outdir/'animation_tracks.csv',outdir/'animation_timeline.csv']
    missing=[p.name for p in required if not p.exists()]
    if missing:
        raise FileNotFoundError('Missing saved analysis files: '+', '.join(missing))

    cells=[]
    with (outdir/'ss6_cellmap.csv').open(newline='',encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            cells.append(Cell(
                int(row['cell_id']),int(row['record_offset_hex'],16),int(row.get('cell_id') or 0),
                int(row.get('cell_index') or 0),row.get('cell_name',''),int(float(row['x'])),int(float(row['y'])),
                int(float(row['width'])),int(float(row['height'])),float(row.get('pivot_x') or 0),float(row.get('pivot_y') or 0),
                row.get('record_type') or '70',str(row.get('geometry_available','True')).lower()=='true'))

    if Image:
        try:
            source=preferred_texture(res)
            if source and source.exists():
                atlas=Image.open(source).convert('RGBA')
                origin=make_atlas_origin_cell(atlas,cells)
                if origin is not None and not any(c.geometry_available and c.cell_id==0 for c in cells):
                    cells.insert(0,origin)
            # If a new _normal/_mreo was added since the original analysis,
            # regenerate only the missing texture crop sets as part of reload.
            export_texture_crops(res,outdir,cells,True,only_missing=True)
        except Exception:
            pass

    refs=[]
    with (outdir/'cell_references.csv').open(newline='',encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            refs.append(CellReference(int(row['order']),int(row['offset_hex'],16),row['name'],int(row['length'])))

    groups={}
    with (outdir/'animation_tracks.csv').open(newline='',encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            tid=int(row['track_id'])
            if tid not in groups:
                groups[tid]=Track(tid,row['animation'],int(row['animation_index']),row['part'],int(row['part_index']),
                                  int(row['frame_count']),int(row['end_frame']),int(row['fps']),[])
            groups[tid].keys.append({
                'animation':row['animation'],'animation_index':int(row['animation_index']),'part':row['part'],
                'part_index':int(row['part_index']),'key_index':int(row['key_index']),'frame':int(row['frame']),
                'iptype':row['iptype'],'reference':row['reference'],'reference_order':int(row['reference_order']),
                'reference_offset':None,'cell_id':int(row['cell_id']) if row['cell_id'] else None,
                'x':int(float(row['x'])) if row['x'] else None,'y':int(float(row['y'])) if row['y'] else None,
                'width':int(float(row['width'])) if row['width'] else None,'height':int(float(row['height'])) if row['height'] else None,
                'record_offset':int(row['record_offset_hex'],16) if row['record_offset_hex'] else None,
                'record_type':row.get('record_type') or None,
                'geometry_available':str(row.get('geometry_available','False')).lower()=='true'})
    tracks=[groups[k] for k in sorted(groups)]
    animations=[]
    seen={}
    for t in tracks:
        if t.animation_index not in seen:
            seen[t.animation_index]={'index':t.animation_index,'name':t.animation,'frame_count':t.frame_count,'end_frame':t.end_frame,'fps':t.fps,'part_count':0,'header_type':'Cached'}
        seen[t.animation_index]['part_count']+=1
    animations=[seen[k] for k in sorted(seen)]
    unresolved=[]
    unresolved_path=outdir/'unresolved_references.csv'
    if unresolved_path.exists():
        with unresolved_path.open(newline='',encoding='utf-8-sig') as f:
            unresolved=[CellReference(int(r['order']),int(r['offset_hex'],16),r['name'],int(r['length'])) for r in csv.DictReader(f)]
    unreferenced=[]
    unref_path=outdir/'unreferenced_cells.csv'
    if unref_path.exists():
        with unref_path.open(newline='',encoding='utf-8-sig') as f:
            for r in csv.DictReader(f):
                unreferenced.append(Cell(int(r['cell_id']),int(r['record_offset_hex'],16),0,0,r['cell_name'],int(float(r['x'])),int(float(r['y'])),int(float(r['width'])),int(float(r['height'])),0,0))
    summary={'version':APP_VERSION,'uasset':str(res.uasset),'uexp':str(res.uexp),'texture':str(res.tex) if res.tex else None,
             'textures':{k:str(v) if v else None for k,v in res.textures().items()},
             'cell_count':len(cells),'cell_reference_count':len(refs),'animation_count':len(animations),
             'part_count':len({(t.animation_index,t.part_index) for t in tracks}),'cell_key_count':sum(len(t.keys) for t in tracks),
             'track_count':len(tracks),'resolved_reference_count':len(refs)-len(unresolved),
             'unresolved_reference_count':len(unresolved),'special_reference_count':sum(1 for t in tracks for k in t.keys if k.get('record_type') not in (None,'70','78')),
             'non_cell_reference_count':max(0,len(refs)-sum(len(t.keys) for t in tracks)),'unreferenced_cell_count':len(unreferenced),
             'animations':[{'index':a['index'],'name':a['name'],'frame_count':a['frame_count'],'end_frame':a['end_frame'],'fps':a['fps'],'part_count':a['part_count'],'header_type':a['header_type']} for a in animations]}
    return {'cells':cells,'refs':refs,'tracks':tracks,'animations':animations,'unresolved_refs':unresolved,'unreferenced':unreferenced,'cell_records':{},'summary':summary}


def analysis_cache_status(outdir:Path):
    required=['ss6_cellmap.csv','cell_references.csv','animation_tracks.csv','animation_timeline.csv']
    return outdir.exists() and all((outdir/n).is_file() for n in required)


def save_analysis(res:Resource,outdir:Path,export_crops=True,annotate_atlas=True):
    outdir.mkdir(parents=True,exist_ok=True)
    names,animations,part_total,cell_keys=parse_animations(res.uasset,res.uexp)
    cells,cell_records=parse_cell_defs(res.uexp,names)
    refs=parse_cell_refs(res.uexp)
    tracks=resolve_tracks(animations,refs,cells,cell_records)
    # Only references actually consumed by Cell tracks are tested here.
    # FFRS also stores event/reference strings such as footstep/rope in the same
    # global reference stream; those are not unresolved Cell references.
    used_ref_orders={k['reference_order'] for t in tracks for k in t.keys}
    unresolved_refs=[r for r in refs if r.order in used_ref_orders and r.name not in cell_records]
    referenced_ids={cell_records[r.name].cell_id for r in refs if r.name in cell_records and cell_records[r.name].geometry_available and cell_records[r.name].cell_id}
    unreferenced=[c for c in cells if c.cell_id not in referenced_ids]

    atlas_im=None
    source_texture=preferred_texture(res)
    if source_texture and source_texture.exists() and Image:
        atlas_im=Image.open(source_texture).convert('RGBA')
        origin=make_atlas_origin_cell(atlas_im,cells)
        if origin is not None:
            cells.insert(0,origin)
            unreferenced.insert(0,origin)

    with (outdir/'ss6_cellmap.csv').open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.writer(f);w.writerow(['cell_id','cell_name','cell_ref_name','cellmap_name','cell_index','x','y','width','height','pivot_x','pivot_y','record_type','geometry_available','record_offset_hex','texture_png'])
        for c in cells:
            w.writerow([c.cell_id,c.name,cell_ref_name(c),c.name,c.sub_index,c.x,c.y,c.width,c.height,round(c.pivot_x,6),round(c.pivot_y,6),c.record_type,c.geometry_available,hex(c.record_offset),str(res.tex or source_texture) if (res.tex or source_texture) else ''])
    with (outdir/'cell_references.csv').open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.writer(f);w.writerow(['order','name','offset_hex','length'])
        for r in refs:w.writerow([r.order,r.name,hex(r.offset),r.length])
    with (outdir/'animation_tracks.csv').open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.writer(f);w.writerow(['track_id','animation','animation_index','part','part_index','frame_count','end_frame','fps','key_index','frame','iptype','reference','reference_order','cell_id','x','y','width','height','record_type','geometry_available','record_offset_hex'])
        for t in tracks:
            for k in t.keys:w.writerow([t.track_id,t.animation,t.animation_index,t.part,t.part_index,t.frame_count,t.end_frame,t.fps,k['key_index'],k['frame'],k['iptype'],k['reference'],k['reference_order'],k['cell_id'] or '',k['x'] if k['x'] is not None else '',k['y'] if k['y'] is not None else '',k['width'] if k['width'] is not None else '',k['height'] if k['height'] is not None else '',k.get('record_type') or '',k.get('geometry_available',False),hex(k['record_offset']) if k['record_offset'] is not None else ''])
    with (outdir/'animation_timeline.csv').open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.writer(f);w.writerow(['animation','part','part_index','frame_start','frame_end','crop_id','reference','resolved','x','y','width','height','record_type','geometry_available'])
        for t in tracks:
            for i,k in enumerate(t.keys):
                end=(t.keys[i+1]['frame']-1) if i+1<len(t.keys) else t.end_frame
                w.writerow([t.animation,t.part,t.part_index,k['frame'],end,k['cell_id'] or '',k['reference'],bool(k['cell_id']),k['x'] if k['x'] is not None else '',k['y'] if k['y'] is not None else '',k['width'] if k['width'] is not None else '',k['height'] if k['height'] is not None else '',k.get('record_type') or '',k.get('geometry_available',False)])
    with (outdir/'unresolved_references.csv').open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.writer(f);w.writerow(['order','name','offset_hex','length'])
        for r in unresolved_refs:w.writerow([r.order,r.name,hex(r.offset),r.length])
    with (outdir/'unreferenced_cells.csv').open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.writer(f);w.writerow(['cell_id','cell_name','cell_ref_name','x','y','width','height','record_offset_hex'])
        for c in unreferenced:w.writerow([c.cell_id,c.name,cell_ref_name(c),c.x,c.y,c.width,c.height,hex(c.record_offset)])
    (outdir/'unresolved_references.txt').write_text(('None.\n' if not unresolved_refs else '\n'.join(f'#{r.order:03d} {r.name} @ {r.offset:#x}' for r in unresolved_refs))+'\n',encoding='utf-8')
    (outdir/'unreferenced_cells.txt').write_text(('None.\n' if not unreferenced else '\n'.join(f'#{c.cell_id:04d} {cell_ref_name(c)} rect=({c.x},{c.y},{c.width},{c.height})' for c in unreferenced))+'\n',encoding='utf-8')

    if atlas_im is not None:
        im=atlas_im
        # _tex is the preview/annotation texture, while all available variants
        # receive the same Cell rectangles and stable filenames.
        export_texture_crops(res,outdir,cells,export_crops)
        if annotate_atlas and res.tex and res.tex.exists():
            ann=im.copy();d=ImageDraw.Draw(ann)
            try:font=ImageFont.truetype('arial.ttf',10)
            except Exception:font=ImageFont.load_default()
            for c in cells:
                d.rectangle((c.x,c.y,c.x+c.width,c.y+c.height),outline=(255,80,0,255),width=1)
                txt=str(c.cell_id);bb=d.textbbox((0,0),txt,font=font);tw=bb[2]-bb[0];th=bb[3]-bb[1]
                d.rectangle((c.x,c.y,c.x+tw+3,c.y+th+2),fill=(0,0,0,180));d.text((c.x+1,c.y+1),txt,fill=(255,255,0,255),font=font)
            ann.save(outdir/'atlas_annotated.png')

    summary={'version':APP_VERSION,'uasset':str(res.uasset),'uexp':str(res.uexp),'texture':str(res.tex) if res.tex else None,
             'textures':{k:str(v) if v else None for k,v in res.textures().items()},
             'cell_count':len(cells),'cell_reference_count':len(refs),'animation_count':len(animations),
             'part_count':part_total,'cell_key_count':len(cell_keys),'track_count':len(tracks),
             'resolved_reference_count':len(refs)-len(unresolved_refs),'unresolved_reference_count':len(unresolved_refs),
             'special_reference_count':sum(1 for t in tracks for k in t.keys if k.get('record_type') not in (None,'70','78')),
             'non_cell_reference_count':len(refs)-len(used_ref_orders),
             'unreferenced_cell_count':len(unreferenced),
             'animations':[{'index':a['index'],'name':a['name'],'frame_count':a['frame_count'],'end_frame':a['end_frame'],'fps':a['fps'],'part_count':a['part_count'],'header_type':a['header_type']} for a in animations]}
    (outdir/'analysis_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    return {'cells':cells,'refs':refs,'tracks':tracks,'animations':animations,'unresolved_refs':unresolved_refs,'unreferenced':unreferenced,'cell_records':cell_records,'summary':summary}


def recover_sprite(cellmap:Path,original:Path,crops_dir:Path,output:Path):
    """Restore modified crops to the original sprite using the binary CellMap.

    The numeric prefix in an Analyzer crop filename is the stable Cell ID from
    the CellMap used when the crop was exported.  It is therefore the primary
    compatibility key.  The filename text is only a fallback/diagnostic: older
    releases used slightly different Cell names (for example ``AB_bunshinken``
    versus ``AB_bunshinken00``), and some names themselves end in ``_0``/``_1``.

    A crop must keep the original Cell dimensions.  Unmatched crops are
    reported and skipped rather than aborting the whole recovery; this is
    important for legacy crops whose Cell record is genuinely absent from the
    current UEXP.  Successfully matched crops are still written to the output.
    """
    if Image is None:
        raise RuntimeError('Pillow is required.')

    rows=[]
    with cellmap.open('r',newline='',encoding='utf-8-sig') as f:
        for i,row in enumerate(csv.DictReader(f),1):
            try:
                cid=int(row.get('cell_id') or row.get('id') or i)
                rows.append({
                    'id':cid,
                    'name':row.get('cell_name',''),
                    'sub':int(row.get('cell_index') or 0),
                    'x':int(float(row['x'])),'y':int(float(row['y'])),
                    'w':int(float(row['width'])),'h':int(float(row['height']))
                })
            except (KeyError,ValueError) as e:
                raise RuntimeError(f'Invalid ss6_cellmap.csv row {i}: {e}')

    by_id={r['id']:r for r in rows}
    by_name=defaultdict(list)
    for r in rows:
        if r['name']:
            by_name[r['name']].append(r)

    def filename_parts(path):
        """Return ordinal and the untouched filename payload.

        Do not parse the final ``_<number>`` as a Cell sub-index here: a Cell
        name can legitimately end in a numeric suffix (e.g. ``swingsword_02``).
        """
        m=re.match(r'^\s*(\d+)_(.+?)\.png$',path.name,re.I)
        if not m:
            return None,None
        return int(m.group(1)),m.group(2)

    def name_variants(payload):
        out=[payload]
        # Current Analyzer names can be ``Name`` while legacy crops can be
        # ``Name_0``/``Name_1``.  Keep the full payload first and only then try
        # the conservative suffix removal.
        m=re.match(r'^(.*)_(\d+)$',payload)
        if m and m.group(1) not in out:
            out.append(m.group(1))
        return out

    base=Image.open(original).convert('RGBA')
    result=base.copy(); replaced=[]; skipped=[]; errors=[]

    for p in sorted(crops_dir.glob('*.png')):
        ordinal,payload=filename_parts(p)
        if ordinal is None:
            skipped.append((p.name,'unrecognized crop filename'))
            continue
        try:
            im=Image.open(p).convert('RGBA')
        except Exception as e:
            errors.append(f'{p.name}: {e}')
            continue

        c=None; match_mode=''

        # 1) Primary compatibility rule: Cell ID + exact dimensions.
        # This handles crops exported by older versions whose Cell names differ
        # from the names recovered from the cooked UEXP.
        id_cell=by_id.get(ordinal)
        if id_cell and im.size==(id_cell['w'],id_cell['h']):
            c=id_cell
            match_mode='cell_id+size'

        # 2) If the old ID ordering differs, try the full filename payload and
        # its conservative numeric-suffix variant, always requiring dimensions.
        if c is None:
            candidates=[]
            for nm in name_variants(payload):
                candidates.extend([x for x in by_name.get(nm,[]) if im.size==(x['w'],x['h'])])
            # Deduplicate by Cell ID.
            uniq={x['id']:x for x in candidates}
            if len(uniq)==1:
                c=next(iter(uniq.values()))
                match_mode='name+size'
            elif len(uniq)>1:
                # If one candidate has the filename's numeric ID, use it;
                # otherwise refuse to guess.
                c=uniq.get(ordinal)
                if c is not None:
                    match_mode='name+size+cell_id'

        # 3) Last compatibility fallback: exact Cell ID even if dimensions do
        # not match is NOT accepted. A modified crop must retain its geometry.
        if c is None:
            expected=f'Cell #{ordinal}'
            if id_cell:
                expected+=f" '{id_cell['name']}' expected {id_cell['w']}x{id_cell['h']}"
            errors.append(f'{p.name}: Cell not found in current UEXP CellMap ({expected})')
            continue

        if im.size!=(c['w'],c['h']):
            errors.append(f"{p.name}: size {im.size} != expected {(c['w'],c['h'])} for Cell #{c['id']} '{c['name']}'")
            continue

        x,y,w,h=c['x'],c['y'],c['w'],c['h']
        if x<0 or y<0 or x+w>result.width or y+h>result.height:
            errors.append(f'{p.name}: Cell #{c["id"]} rectangle ({x},{y},{w},{h}) is outside original image')
            continue
        result.paste(im,(x,y))
        replaced.append((c['id'],c['name'],p.name,x,y,w,h,match_mode))

    output.parent.mkdir(parents=True,exist_ok=True)
    result.save(output)

    report=output.with_name(output.stem+'_recovery_report.csv')
    with report.open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.writer(f)
        w.writerow(['status','cell_id','cell_name','crop','x','y','width','height','match','message'])
        for r in replaced:w.writerow(['replaced',*r,''])
        for r in skipped:w.writerow(['skipped','','',r[0],'','','','','',r[1]])
        for msg in errors:w.writerow(['unmatched','','','','','','','','',msg])

    # Recovery is successful as long as at least one crop was restored.  If all
    # crops failed, surface the first errors so the user gets a useful reason.
    if not replaced and errors:
        try: output.unlink()
        except OSError: pass
        raise RuntimeError('No crop could be restored; no output PNG was written.\n'+'\n'.join(errors[:20]))
    return len(replaced),len(skipped),errors


def _texture_kind_from_path(path:Path):
    stem=path.stem
    for kind in ('tex','normal','mreo'):
        suffix='_'+kind
        if stem.endswith(suffix):
            return kind,stem[:-len(suffix)]
    return 'tex',stem


def sibling_texture(path:Path,kind:str):
    _,base=_texture_kind_from_path(path)
    return path.with_name(f'{base}_{kind}.png')


def _crop_dirs_from_selected(selected:Path):
    """Resolve the three crop directories from any one selected crop dir."""
    if selected.name.lower() in ('crops','crops_normal','crops_mreo'):
        parent=selected.parent
    else:
        parent=selected
    return {
        'tex':parent/'crops',
        'normal':parent/'crops_normal',
        'mreo':parent/'crops_mreo',
    }


def _output_for_kind(selected:Path,kind:str,selected_kind:str):
    if kind==selected_kind:
        return selected
    stem=selected.stem
    # Strip the selected texture suffix while preserving the user's chosen
    # recovered-output naming convention.
    stem=re.sub(r'_(?:tex|normal|mreo)_recovered$','_recovered',stem)
    if stem.endswith('_recovered'):
        stem=stem[:-len('_recovered')] + f'_{kind}_recovered'
    else:
        stem=stem + f'_{kind}_recovered'
    return selected.with_name(stem+'.png')


def recover_texture_set(cellmap:Path,original:Path,crops_selected:Path,output_selected:Path):
    """Recover every available FFRS texture variant from one recovery setup.

    The selected original may be _tex, _normal, or _mreo.  Its sibling texture
    files and the three shared crop directories are discovered automatically.
    Missing variants are simply skipped.
    """
    if Image is None:
        raise RuntimeError('Pillow is required.')
    selected_kind,_=_texture_kind_from_path(original)
    crop_dirs=_crop_dirs_from_selected(crops_selected)
    kinds=[]
    for kind in ('tex','normal','mreo'):
        src=original if kind==selected_kind else sibling_texture(original,kind)
        crop_dir=crop_dirs[kind]
        if src.exists() and crop_dir.is_dir():
            kinds.append((kind,src,crop_dir,_output_for_kind(output_selected,kind,selected_kind)))
    if not kinds:
        raise FileNotFoundError('No matching texture + crop set was found for _tex/_normal/_mreo.')
    results=[]
    for kind,src,crop_dir,out in kinds:
        r=recover_sprite(cellmap,src,crop_dir,out)
        results.append((kind,src,out,r))
    return results


I18N={
'zh':{'title':'Sprite 切片分析器 v1.0','heading':'FFRS Sprite Slice Analyzer v1.0','subtitle':'从游戏解包资源解析单元格与动画播放顺序','language':'语言 / Language','input':'输入目录','resource':'角色资源','out':'输出目录','choose':'选择...','refresh':'扫描','run':'开始解析','recover':'还原修改后的 Sprite','recover_original':'原始精灵片（_tex / _normal / _mreo）','recover_crops':'修改后的切片（自动识别三套）','recover_output':'还原输出精灵片（自动生成三套）','auto':'输入目录下使用 char 为主资源，other 仅作为独立资源扫描','crops':'导出切片和带编号的切片','annotate':'生成带编号 Atlas','tracks':'播放轨道','view':'轨道','preview':'切片预览','frames':'关键帧','prev':'上一键','next':'下一键','play':'播放','pause':'暂停','speed':'播放速度','raw':'原始切片','export_png':'导出当前轨道','export_gif':'导出 GIF','details':'当前切片','status_ready':'v1.0：等待解析。','starting':'正在解析动画与 Cell 数据…','done':'完成：{a} 个动画，{p} 个 Part，{k} 个 Cell Key，{c} 个 Cell，{r} 个引用；{u} 个引用暂时无 Cell 定义。','cache_found':'检测到该资源已有解析数据：\n{out}\n\n是否直接读取已有解析数据并加载到预览？','cache_loaded':'已读取已有解析数据：{a} 个动画，{p} 个 Part，{k} 个 Cell Key，{c} 个 Cell。','overwrite_confirm':'已存在解析数据。\n{out}\n\n确定要重新解析并覆盖这些文件吗？','error':'错误：{e}','no_resource':'char 中没有找到完整的 UAsset + UEXP。','no_png':'没有找到对应 Sprite PNG，仍可生成二进制解析结果。','need_analysis':'请先完成一次解析。','recover_need_original':'请选择原始精灵片 PNG。','recover_need_crops':'请选择切片目录。','recover_done':'精灵片还原完成：{out}','recover_report':'还原结果：成功 {r}，跳过 {s}，未匹配 {u}。详细记录：{out}','no_data':'没有可导出的数据。','exported':'已导出：{out}','unresolved':'未解析引用','cell':'Cell','reference':'引用','rect':'XYWH','frame':'Frame','animation':'Animation','part':'Part','fps':'FPS','resolved':'已解析','version':'版本'},
'en':{'title':'Sprite Slice Analyzer v1.0','heading':'FFRS Sprite Slice Analyzer v1.0','subtitle':'Parse Cells and animation playback order from unpacked game resources.','language':'语言 / Language','input':'Input directory','resource':'Character resource','out':'Output folder','choose':'Choose...','refresh':'Scan','run':'Analyze','recover':'Recover Modified Sprite','recover_original':'Original Sprite / Atlas (_tex / _normal / _mreo)','recover_crops':'Modified crops (auto-detect all 3)','recover_output':'Recovered PNGs (auto-generate all 3)','auto':'char is the primary resource folder; other is scanned separately','crops':'Export crops and crops_numbered','annotate':'Generate numbered Atlas','tracks':'Cell playback tracks','view':'Tracks','preview':'Crop preview','frames':'Cell Key timeline','prev':'Previous key','next':'Next key','play':'Play','pause':'Pause','speed':'Speed','raw':'Raw crop','export_png':'Export current track','export_gif':'Export GIF','details':'Current crop','status_ready':'v1.0: Ready.','starting':'Parsing animation and Cell data…','done':'Done: {a} animations, {p} Parts, {k} Cell Keys, {c} Cells, {r} references; {u} references currently have no Cell definition.','cache_found':'Saved analysis data already exists:\n{out}\n\nLoad the existing data into the preview instead of parsing again?','cache_loaded':'Loaded saved analysis: {a} animations, {p} Parts, {k} Cell Keys, {c} Cells.','overwrite_confirm':'Saved analysis data already exists.\n{out}\n\nRe-analyze and overwrite the existing files?','error':'Error: {e}','no_resource':'No complete UAsset + UEXP found in char.','no_png':'No matching Sprite PNG found; binary results can still be generated.','need_analysis':'Run analysis first.','recover_need_original':'Select the original Sprite/Atlas PNG.','recover_need_crops':'Select the crops directory.','recover_done':'Sprite recovery complete: {out}','recover_report':'Recovery result: {r} restored, {s} skipped, {u} unmatched. Detailed report: {out}','no_data':'No data to export.','exported':'Exported: {out}','unresolved':'Unresolved reference','cell':'Cell','reference':'Reference','rect':'XYWH','frame':'Frame','animation':'Animation','part':'Part','fps':'FPS','resolved':'Resolved','version':'Version'}}
class App(tk.Tk):
    def __init__(self):
        super().__init__();self.language=tk.StringVar(value='zh');self.vars={k:tk.StringVar() for k in ['input','resource','out','recover_original','recover_crops','recover_output']};self.crops=tk.BooleanVar(value=True);self.annotate=tk.BooleanVar(value=True);self.resources=[];self.current=None;self.result=None;self.tracks=[];self.filtered=[];self.current_track=None;self.current_index=0;self.playing=False;self.after_id=None;self.play_speed=tk.StringVar(value='1x');self.im=None;self.build_ui();self.load_settings();self.apply_language();self.protocol('WM_DELETE_WINDOW',self.close)
    def t(self,msg_key,**kw): return I18N[self.language.get()][msg_key].format(**kw)
    def build_ui(self):
        self.geometry('1200x820');self.minsize(980,700);self.columnconfigure(0,weight=1);self.rowconfigure(4,weight=1)
        top=ttk.Frame(self,padding=(12,10,12,8));top.grid(row=0,column=0,sticky='ew');top.columnconfigure(1,weight=1)
        self.heading=ttk.Label(top,font=('Segoe UI',16,'bold'));self.heading.grid(row=0,column=0,sticky='w');self.lang_label=ttk.Label(top);self.lang_label.grid(row=0,column=2,sticky='e',padx=(12,5));self.lang_combo=ttk.Combobox(top,state='readonly',values=['中文','English'],width=10);self.lang_combo.grid(row=0,column=3,sticky='e');self.lang_combo.bind('<<ComboboxSelected>>',self.on_lang)
        self.subtitle=ttk.Label(top);self.subtitle.grid(row=1,column=0,columnspan=4,sticky='w',pady=(3,0))

        form=ttk.Frame(self,padding=(12,0,12,6));form.grid(row=1,column=0,sticky='ew');form.columnconfigure(1,weight=1)
        self.labels={};self.buttons={}; self.form_entries={}
        for row,k in enumerate(['input','resource','out']):
            self.labels[k]=ttk.Label(form);self.labels[k].grid(row=row,column=0,sticky='w',padx=(0,8),pady=(0,5))
            if k=='resource':
                self.resource_combo=ttk.Combobox(form,state='readonly');self.resource_combo.grid(row=row,column=1,sticky='ew',pady=(0,5));self.resource_combo.bind('<<ComboboxSelected>>',self.on_resource);self.form_entries[k]=self.resource_combo
            else:
                ent=ttk.Entry(form,textvariable=self.vars[k]);ent.grid(row=row,column=1,sticky='ew',pady=(0,5));self.form_entries[k]=ent
            self.buttons[k]=ttk.Button(form,width=8,command=(self.scan_input if k=='resource' else lambda kk=k:self.pick(kk)));self.buttons[k].grid(row=row,column=2,sticky='e',padx=(8,0),pady=(0,5))
        self.crops_cb=ttk.Checkbutton(form,variable=self.crops);self.crops_cb.grid(row=3,column=0,columnspan=2,sticky='w',pady=(3,0));self.annotate_cb=ttk.Checkbutton(form,variable=self.annotate);self.annotate_cb.grid(row=4,column=0,columnspan=2,sticky='w',pady=(2,0));self.run_btn=ttk.Button(form,width=12,command=self.run);self.run_btn.grid(row=3,column=2,rowspan=2,sticky='e',pady=(3,0))
        self.warning=ttk.Label(self,padding=(12,2));self.warning.grid(row=2,column=0,sticky='ew')

        rec=ttk.LabelFrame(self,padding=(10,8));rec.grid(row=3,column=0,sticky='ew',padx=12,pady=(2,2));rec.columnconfigure(1,weight=1)
        self.recover_entries={};self.recover_browse={}
        for row,k in enumerate(['recover_original','recover_crops','recover_output']):
            lab=ttk.Label(rec);lab.grid(row=row,column=0,sticky='w',padx=(0,8),pady=(0,5));self.recover_entries[k]=lab
            ttk.Entry(rec,textvariable=self.vars[k]).grid(row=row,column=1,sticky='ew',pady=(0,5))
            self.recover_browse[k]=ttk.Button(rec,text='...',width=8,command=lambda kk=k:self.pick_recover(kk));self.recover_browse[k].grid(row=row,column=2,sticky='e',padx=(8,0),pady=(0,5))
        self.recover_btn=ttk.Button(rec,width=18,command=self.recover);self.recover_btn.grid(row=3,column=2,sticky='e',pady=(2,0))
        pan=ttk.Panedwindow(self,orient='horizontal');pan.grid(row=4,column=0,sticky='nsew',padx=10,pady=5);self.rowconfigure(4,weight=1)
        left=ttk.Frame(pan,padding=5);mid=ttk.Frame(pan,padding=5);right=ttk.Frame(pan,padding=5);pan.add(left,weight=2);pan.add(mid,weight=4);pan.add(right,weight=2)
        self.tracks_label=ttk.Label(left);self.tracks_label.pack(anchor='w');self.track_list=tk.Listbox(left,exportselection=False);self.track_list.pack(fill='both',expand=True,pady=5);self.track_list.bind('<<ListboxSelect>>',self.on_track)
        self.preview_label=ttk.Label(mid);self.preview_label.pack(anchor='w');self.canvas=tk.Canvas(mid,bg='#202020',highlightthickness=0);self.canvas.pack(fill='both',expand=True,pady=5);self.canvas.bind('<Configure>',lambda e:self.show())
        ctl=ttk.Frame(mid);ctl.pack(fill='x');self.prev_btn=ttk.Button(ctl,command=lambda:self.step(-1));self.prev_btn.pack(side='left');self.play_btn=ttk.Button(ctl,command=self.toggle);self.play_btn.pack(side='left',padx=4);self.next_btn=ttk.Button(ctl,command=lambda:self.step(1));self.next_btn.pack(side='left');self.speed_label=ttk.Label(ctl);self.speed_label.pack(side='left',padx=(14,4));self.speed_combo=ttk.Combobox(ctl,textvariable=self.play_speed,state='readonly',width=7,values=['0.25x','0.5x','0.75x','1x','1.5x','2x']);self.speed_combo.pack(side='left');self.speed_combo.current(1);self.speed_combo.bind('<<ComboboxSelected>>',lambda e:self.save_settings());self.export_btn=ttk.Button(ctl,command=self.export_track);self.export_btn.pack(side='right');self.gif_btn=ttk.Button(ctl,command=self.export_gif);self.gif_btn.pack(side='right',padx=4)
        self.frames_label=ttk.Label(right);self.frames_label.pack(anchor='w');self.frame_list=tk.Listbox(right,exportselection=False);self.frame_list.pack(fill='both',expand=True,pady=5);self.frame_list.bind('<<ListboxSelect>>',self.on_frame);self.details=ttk.LabelFrame(right);self.details.pack(fill='x');self.detail_text=tk.Text(self.details,height=11,wrap='word');self.detail_text.pack(fill='both',expand=True)
        self.status=tk.StringVar();ttk.Label(self,textvariable=self.status,anchor='w').grid(row=5,column=0,sticky='ew',padx=12,pady=4)
    def on_lang(self,_=None):self.language.set('zh' if self.lang_combo.get()=='中文' else 'en');self.apply_language();self.save_settings()
    def apply_language(self):
        self.title(self.t('title'));self.heading.config(text=self.t('heading'));self.subtitle.config(text=self.t('subtitle'));self.lang_label.config(text=self.t('language'));self.lang_combo.set('中文' if self.language.get()=='zh' else 'English')
        for k,lab in self.labels.items():lab.config(text=self.t(k))
        self.buttons['input'].config(text=self.t('choose'));self.buttons['resource'].config(text=self.t('refresh'));self.buttons['out'].config(text=self.t('choose'));self.crops_cb.config(text=self.t('crops'));self.annotate_cb.config(text=self.t('annotate'));self.run_btn.config(text=self.t('run'));self.warning.config(text=self.t('auto'));self.recover_btn.config(text=self.t('recover'));self.recover_entries['recover_original'].config(text=self.t('recover_original'));self.recover_entries['recover_crops'].config(text=self.t('recover_crops'));self.recover_entries['recover_output'].config(text=self.t('recover_output'));[self.recover_browse[k].config(text=self.t('choose')) for k in self.recover_browse];self.tracks_label.config(text=self.t('tracks'));self.preview_label.config(text=self.t('preview'));self.frames_label.config(text=self.t('frames'));self.prev_btn.config(text=self.t('prev'));self.next_btn.config(text=self.t('next'));self.play_btn.config(text=self.t('pause') if self.playing else self.t('play'));self.speed_label.config(text=self.t('speed'));self.export_btn.config(text=self.t('export_png'));self.gif_btn.config(text=self.t('export_gif'));self.status.set(self.t('status_ready') if not self.result else self.status.get());self.refresh_tracks()
    def pick(self,k):
        p=filedialog.askdirectory();
        if p:self.vars[k].set(p);self.scan_input() if k=='input' else None
    def pick_recover(self,k):
        if k=='recover_original':p=filedialog.askopenfilename(filetypes=[('PNG','*.png'),('All','*.*')])
        elif k=='recover_crops':p=filedialog.askdirectory()
        else:p=filedialog.asksaveasfilename(defaultextension='.png',filetypes=[('PNG','*.png')])
        if p:self.vars[k].set(p);self.save_settings()
    def scan_input(self):
        root=Path(self.vars['input'].get())
        if not root:return
        selected=self.resource_combo.get().strip() if hasattr(self,'resource_combo') else ''
        if not selected:selected=self.vars['resource'].get().strip()
        root.mkdir(parents=True,exist_ok=True);(root/'char').mkdir(exist_ok=True);(root/'other').mkdir(exist_ok=True)
        self.resources=discover_resources(root,'char')
        labels=[r.stem for r in self.resources]
        self.resource_combo['values']=labels
        if self.resources:
            idx=labels.index(selected) if selected in labels else 0
            self.resource_combo.current(idx)
            self.current=self.resources[idx]
            self.vars['resource'].set(labels[idx])
        else:
            self.current=None;self.vars['resource'].set('');self.resource_combo.set('')
        if not self.vars['out'].get():self.vars['out'].set(str(root/'analysis'))
        self.status.set(f"char={len(self.resources)}" + (f" | {self.current.stem}: " + ','.join(k for k,v in self.current.textures().items() if v) if self.current else ''))

    def on_resource(self,_=None):
        i=self.resource_combo.current()
        if 0<=i<len(self.resources):
            self.current=self.resources[i]
            self.vars['resource'].set(self.resources[i].stem)
            self.im=None
            self.result=None;self.tracks=[];self.filtered=[];self.current_track=None
            self.refresh_tracks()

    def run(self):
        try:
            self.run_btn.config(state='disabled');self.status.set(self.t('starting'));self.update_idletasks();self.scan_input()
            if not self.resources:raise FileNotFoundError(self.t('no_resource'))
            if not self.current:self.current=self.resources[0]
            out=Path(self.vars['out'].get())/self.current.stem
            if analysis_cache_status(out):
                use_cache=messagebox.askyesno(self.t('title'),self.t('cache_found',out=out),default=messagebox.YES)
                if use_cache:
                    self.result=load_saved_analysis(self.current,out)
                    self.tracks=self.result['tracks'];self.filtered=self.tracks
                    if self.current.png:self.vars['recover_original'].set(str(self.current.png))
                    elif preferred_texture(self.current):self.vars['recover_original'].set(str(preferred_texture(self.current)))
                    self.vars['recover_crops'].set(str(out/'crops'));self.vars['recover_output'].set(str(out/(self.current.stem+'_recovered.png')))
                    s=self.result['summary'];self.status.set(self.t('cache_loaded',a=s['animation_count'],p=s['part_count'],k=s['cell_key_count'],c=s['cell_count']))
                    self.refresh_tracks();return
                if not messagebox.askyesno(self.t('title'),self.t('overwrite_confirm',out=out),default=messagebox.NO):
                    self.status.set(self.t('status_ready'));return
            self.result=save_analysis(self.current,out,self.crops.get(),self.annotate.get());self.tracks=self.result['tracks'];self.filtered=self.tracks
            if self.current.png:self.vars['recover_original'].set(str(self.current.png))
            elif preferred_texture(self.current):self.vars['recover_original'].set(str(preferred_texture(self.current)))
            self.vars['recover_crops'].set(str(out/'crops'));self.vars['recover_output'].set(str(out/(self.current.stem+'_recovered.png')))
            s=self.result['summary'];self.status.set(self.t('done',a=s['animation_count'],p=s['part_count'],k=s['cell_key_count'],c=s['cell_count'],r=s['cell_reference_count'],u=s['unresolved_reference_count']));self.refresh_tracks();messagebox.showinfo(self.t('title'),self.status.get()+f'\n\n{out}')
        except Exception as e:
            traceback.print_exc();self.status.set(self.t('error',e=e));messagebox.showerror(self.t('title'),str(e))
        finally:self.run_btn.config(state='normal')
    def refresh_tracks(self):
        self.track_list.delete(0,'end')
        for t in self.filtered:
            unresolved=sum(k['cell_id'] is None for k in t.keys);special=sum(not k.get('geometry_available',False) for k in t.keys)
            label=f'[{t.animation}] {t.part} [Part #{t.part_index:02d}]  ({len(t.keys)} keys)'
            if unresolved: label += f'  !{unresolved}'
            if special: label += f'  S{special}'
            self.track_list.insert('end',label)
        if self.filtered:self.track_list.selection_set(0);self.current_track=self.filtered[0];self.load_track()
    def on_track(self,_=None):
        s=self.track_list.curselection();
        if s and s[0]<len(self.filtered):self.current_track=self.filtered[s[0]];self.load_track()
    def load_track(self):
        self.current_index=0;self.playing=False;self.play_btn.config(text=self.t('play'));self.frame_list.delete(0,'end')
        if not self.current_track:return
        t=self.current_track
        for i,k in enumerate(t.keys):
            end=t.keys[i+1]['frame']-1 if i+1<len(t.keys) else t.end_frame;status='?' if k['cell_id'] is None else (f'#{k["cell_id"]:04d}' if k.get('geometry_available',False) else f'#{k["cell_id"]:04d} [Special {k.get("record_type")}]');self.frame_list.insert('end',f'{k["frame"]:03d}-{end:03d}  {status}  {k["reference"]}')
        if t.keys:self.frame_list.selection_set(0);self.show()
    def on_frame(self,_=None):
        s=self.frame_list.curselection();
        if s:self.current_index=s[0];self.show()
    def get_im(self):
        if not self.current or not self.current.png or Image is None:return None
        if self.im is None:self.im=Image.open(self.current.png).convert('RGBA')
        return self.im
    def show(self):
        self.canvas.delete('all');t=self.current_track
        if not t or not t.keys:return
        k=t.keys[self.current_index];im=self.get_im()
        if k['cell_id'] is None:
            self.canvas.create_text(max(20,self.canvas.winfo_width()//2),max(20,self.canvas.winfo_height()//2),text=f'{self.t("unresolved")}\n{k["reference"]}',fill='orange',font=('Segoe UI',18,'bold'))
        elif not k.get('geometry_available',False) or not k.get('width') or not k.get('height'):
            self.canvas.create_text(max(20,self.canvas.winfo_width()//2),max(20,self.canvas.winfo_height()//2),text=f'Special Cell\n{k["reference"]}\nType: {k.get("record_type")}',fill='orange',font=('Segoe UI',18,'bold'))
        elif im is None:
            self.canvas.create_text(max(20,self.canvas.winfo_width()//2),max(20,self.canvas.winfo_height()//2),text=self.t('no_png'),fill='white')
        else:
            cr=im.crop((k['x'],k['y'],k['x']+k['width'],k['y']+k['height']));maxw=max(80,self.canvas.winfo_width()-30);maxh=max(80,self.canvas.winfo_height()-30);scale=min(maxw/cr.width,maxh/cr.height,8);cr=cr.resize((max(1,int(cr.width*scale)),max(1,int(cr.height*scale))),Image.Resampling.NEAREST);self.preview_tk=ImageTk.PhotoImage(cr);self.canvas.create_image(self.canvas.winfo_width()//2,self.canvas.winfo_height()//2,image=self.preview_tk,anchor='center')
        end=t.keys[self.current_index+1]['frame']-1 if self.current_index+1<len(t.keys) else t.end_frame
        self.detail_text.delete('1.0','end');self.detail_text.insert('end',f'{self.t("animation")}: {t.animation}\n{self.t("part")}: {t.part} [#{t.part_index:02d}]\n{self.t("fps")}: {t.fps}\n{self.t("frame")}: {k["frame"]}–{end}\n{self.t("reference")}: {k["reference"]}\n{self.t("cell")}: {k["cell_id"] or "?"}\n{self.t("rect")}: ({k["x"]}, {k["y"]}, {k["width"]}, {k["height"]})\nRecord: {k.get("record_type") or "-"}\nGeometry: {k.get("geometry_available",False)}\nIpType: {k["iptype"]}')
    def step(self,d):
        if not self.current_track or not self.current_track.keys:return
        self.current_index=(self.current_index+d)%len(self.current_track.keys);self.frame_list.selection_clear(0,'end');self.frame_list.selection_set(self.current_index);self.frame_list.see(self.current_index);self.show()
    def toggle(self):
        if not self.current_track or not self.current_track.keys:return
        self.playing=not self.playing;self.play_btn.config(text=self.t('pause') if self.playing else self.t('play'))
        if self.playing:self.tick()
        elif self.after_id:self.after_cancel(self.after_id);self.after_id=None
    def tick(self):
        if not self.playing:return
        self.step(1)
        factor={'0.25x':4.0,'0.5x':2.0,'0.75x':1.333333,'1x':1.0,'1.5x':0.666667,'2x':0.5}.get(self.play_speed.get(),2.0)
        # Preview is intentionally slower than real-time game playback so each
        # crop/key is easy to inspect.  1x = 250 ms per Cell Key.
        delay=max(60,int(250*factor))
        self.after_id=self.after(delay,self.tick)
    def export_track(self):
        if Image is None or not self.current_track or not self.current:messagebox.showwarning(self.t('title'),self.t('no_data'));return
        base_out=Path(self.vars['out'].get())/self.current.stem/'animation_tracks'/safe_name(f'{self.current_track.animation}_{self.current_track.part}_part{self.current_track.part_index:02d}')
        imap={k:Image.open(p).convert('RGBA') for k,p in self.current.textures().items() if p and p.exists()}
        if not imap:return
        paths=[]
        for kind,im in imap.items():
            out=base_out if kind=='tex' else base_out/kind
            out.mkdir(parents=True,exist_ok=True)
            for k in self.current_track.keys:
                if k['cell_id'] is None or not k.get('geometry_available',False) or not k.get('width') or not k.get('height'):continue
                cr=im.crop((k['x'],k['y'],k['x']+k['width'],k['y']+k['height']))
                c_name=safe_name(k.get('reference') or 'Cell'); sub_index=0
                if self.result:
                    for c in self.result.get('cells',[]):
                        if c.cell_id==k['cell_id']:
                            c_name=safe_name(c.name); sub_index=c.sub_index; break
                p=out/f'{k["cell_id"]:04d}_{c_name}_{sub_index}.png'
                cr.save(p);paths.append(p)
        if paths:self.status.set(self.t('exported',out=base_out))
    def export_gif(self):
        if Image is None or not self.current_track or not self.current.png:messagebox.showwarning(self.t('title'),self.t('no_data'));return
        out=Path(self.vars['out'].get())/self.current.stem/'animation_tracks'/safe_name(f'{self.current_track.animation}_{self.current_track.part}_part{self.current_track.part_index:02d}');out.mkdir(parents=True,exist_ok=True);im=self.get_im();frames=[]
        for k in self.current_track.keys:
            if k['cell_id'] is not None and k.get('geometry_available',False) and k.get('width') and k.get('height'):frames.append(im.crop((k['x'],k['y'],k['x']+k['width'],k['y']+k['height'])))
        if not frames:return
        # GIF preview is a convenience export of Cell-key order, not a full
        # multi-Part reconstruction.
        # Normalize all Cell crops onto one transparent canvas. Without this,
        # Pillow may optimize later GIF frames into transparent delta frames,
        # which can make the viewer show previous frames as afterimages.
        max_w=max(f.width for f in frames)
        max_h=max(f.height for f in frames)
        gif_frames=[]
        for f in frames:
            rgba=f.convert('RGBA')
            canvas=Image.new('RGBA',(max_w,max_h),(0,0,0,0))
            canvas.paste(rgba,((max_w-rgba.width)//2,(max_h-rgba.height)//2),rgba)
            gif_frames.append(canvas)
        duration=max(20,int(1000/max(1,self.current_track.fps)))
        gif_frames[0].save(
            out/'cell_key_order.gif',
            save_all=True,
            append_images=gif_frames[1:],
            duration=duration,
            loop=0,
            disposal=2,
            optimize=False,
            transparency=0
        )
        self.status.set(self.t('exported',out=out/'cell_key_order.gif'))
    def recover(self):
        try:
            root=Path(self.vars['out'].get())/self.current.stem if self.current else None
            cellmap=root/'ss6_cellmap.csv' if root else None
            if not cellmap or not cellmap.exists():raise FileNotFoundError(self.t('need_analysis'))
            original=Path(self.vars['recover_original'].get());crops=Path(self.vars['recover_crops'].get());output=Path(self.vars['recover_output'].get())
            if not original.exists():raise FileNotFoundError(self.t('recover_need_original'))
            if not crops.is_dir():raise FileNotFoundError(self.t('recover_need_crops'))
            results=recover_texture_set(cellmap,original,crops,output)
            restored=sum(r[3][0] for r in results);skipped=sum(r[3][1] for r in results);unmatched=sum(len(r[3][2]) for r in results)
            outs='\n'.join(f'{kind}: {out}' for kind,src,out,r in results)
            messagebox.showinfo(self.t('title'),self.t('recover_done',out=outs)+'\n'+self.t('recover_report',r=restored,s=skipped,u=unmatched,out='各贴图对应的 *_recovery_report.csv'))
        except Exception as e:messagebox.showerror(self.t('title'),str(e))
    def load_settings(self):
        try:
            d=json.loads(Path(__file__).with_name('sprite_slice_analyzer_settings.json').read_text(encoding='utf8'));self.language.set(d.get('language','zh'));[self.vars[k].set(v) for k,v in d.get('paths',{}).items() if k in self.vars];self.crops.set(d.get('crops',True));self.annotate.set(d.get('annotate',True));self.play_speed.set(d.get('play_speed','0.5x'))
        except Exception:pass
    def save_settings(self):
        try:Path(__file__).with_name('sprite_slice_analyzer_settings.json').write_text(json.dumps({'language':self.language.get(),'paths':{k:v.get() for k,v in self.vars.items()},'crops':self.crops.get(),'annotate':self.annotate.get(),'play_speed':self.play_speed.get()},ensure_ascii=False,indent=2),encoding='utf8')
        except Exception:pass
    def close(self):self.save_settings();self.destroy()

if __name__=='__main__':
    if Image is None: print('Pillow is required: py -m pip install pillow')
    App().mainloop()
