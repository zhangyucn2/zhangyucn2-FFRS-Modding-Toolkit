# -*- coding: utf-8 -*-
"""FFRS Outline Generator: generate _mreo and correct NVIDIA-generated Normal with the _mreo alpha mask."""
import os, json, threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import numpy as np
from PIL import Image, ImageFilter
from scipy.ndimage import binary_erosion, binary_dilation, distance_transform_edt, gaussian_filter, sobel

APP_VERSION = '1.7'
SETTINGS = 'outline_normal_generator_settings.json'
try:
    import sys as _sys, pathlib as _pl
    _sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))
    from kit import settings as _KIT
    SETTINGS = str(_KIT.state_file('outline_normal_generator_settings.json'))
except Exception:
    pass
DEFAULT_PALETTE = [(40,100,0),(70,120,0),(80,80,0)]

def load_rgba(path):
    return np.array(Image.open(path).convert('RGBA'), dtype=np.uint8, copy=True)

def save_png(arr, path):
    Image.fromarray(np.asarray(arr, dtype=np.uint8), 'RGBA').save(path)

def outline_mask(alpha, mode='inner'):
    opaque = alpha > 0
    cross=np.array([[0,1,0],[1,1,1],[0,1,0]], dtype=bool)
    if mode == 'outer':
        return (~opaque) & binary_dilation(opaque, structure=cross)
    # Matches the samples: outline is the one-pixel inner boundary of opaque pixels.
    return opaque & ~binary_erosion(opaque, structure=cross, border_value=0)

def reference_palette(ref_dir):
    """Build RGB->outline-color examples from paired *_tex.png and *_mreo.png."""
    samples=[]; labels=[]; palette=[]; notes=[]
    if not ref_dir or not os.path.isdir(ref_dir): return None, None, '未使用参考样本'
    for fn in sorted(os.listdir(ref_dir)):
        if not fn.lower().endswith('_tex.png'): continue
        stem=fn[:-8]
        texp=os.path.join(ref_dir,fn)
        candidates=[os.path.join(ref_dir,stem+'_mreo.png'),os.path.join(ref_dir,stem+'_mero.png')]
        mp=next((p for p in candidates if os.path.isfile(p)),None)
        if not mp: continue
        try:
            tex=load_rgba(texp); mr=load_rgba(mp)
            if tex.shape != mr.shape: continue
            mask=outline_mask(tex[:,:,3]) & (mr[:,:,3]>0)
            if not mask.any(): continue
            rgb=tex[:,:,:3][mask].astype(np.int16); col=mr[:,:,:3][mask]
            # Reject near-white/bright pixels in reference mreo: these are usually
            # accidental halos or white fringe and must never become outline colors.
            valid_target = ~((col.min(axis=1) >= 220) & (col.max(axis=1) >= 240))
            rgb=rgb[valid_target]; col=col[valid_target]
            if not len(col): continue
            # Aggregate each exact source RGB to its most common target palette color.
            pairs=np.concatenate([rgb.astype(np.int32),col.astype(np.int32)],axis=1)
            uniq,cnt=np.unique(pairs,axis=0,return_counts=True)
            # Store RGB prototypes, repeated only once; vote per source color.
            src=uniq[:,:3]; dst=uniq[:,3:]
            samples.append(src.astype(np.uint8)); labels.append(dst.astype(np.uint8))
            palette.extend([tuple(map(int,x)) for x in np.unique(col,axis=0) if not (int(np.min(x)) >= 220 and int(np.max(x)) >= 240)])
            notes.append(stem)
        except Exception: pass
    if not samples: return None,None,'未找到成对的 *_tex.png / *_mreo.png 参考样本'
    # collapse exact RGB values across samples by majority vote
    allsrc=np.concatenate(samples); alldst=np.concatenate(labels)
    packed=np.concatenate([allsrc.astype(np.int16),alldst.astype(np.int16)],axis=1)
    uniq,cnt=np.unique(packed,axis=0,return_counts=True)
    # For each source RGB choose target label with highest count.
    mapping={}
    for rgb in np.unique(uniq[:,:3],axis=0):
        ix=np.all(uniq[:,:3]==rgb,axis=1)
        rows=uniq[ix]; counts=cnt[ix]
        target_rows=rows[:,3:]
        target_keys=[tuple(x) for x in target_rows]
        totals={k:int(sum(counts[i] for i,v in enumerate(target_keys) if v==k)) for k in set(target_keys)}
        target=max(totals,key=totals.get)
        if min(target) >= 220 and max(target) >= 240:
            target=min(DEFAULT_PALETTE,key=lambda c:sum((int(c[i])-int(target[i]))**2 for i in range(3)))
        mapping[tuple(map(int,rgb))]=target
    src=np.array(list(mapping.keys()),dtype=np.int16); dst=np.array(list(mapping.values()),dtype=np.uint8)
    return src,dst,'已读取参考样本：'+', '.join(notes)

def classify_outline_colors(tex_rgb, mask, src, dst, palette_mode='reference'):
    out=np.zeros((*mask.shape,4),dtype=np.uint8)
    ys,xs=np.where(mask)
    if len(xs)==0: return out
    pixels=tex_rgb[ys,xs].astype(np.int16)
    if src is not None and len(src):
        # nearest reference edge color in RGB space, processed in chunks to limit memory
        result=np.empty((len(pixels),3),dtype=np.uint8)
        for start in range(0,len(pixels),2048):
            p=pixels[start:start+2048]
            d=((p[:,None,:]-src[None,:,:])**2).sum(axis=2)
            result[start:start+len(p)]=dst[d.argmin(axis=1)]
    else:
        # Conservative fallback: map luminance to the three observed FFRS outline classes.
        lum=(pixels[:,0]*0.299+pixels[:,1]*0.587+pixels[:,2]*0.114)
        result=np.empty((len(pixels),3),dtype=np.uint8)
        result[lum<70]=DEFAULT_PALETTE[0]
        result[(lum>=70)&(lum<155)]=DEFAULT_PALETTE[2]
        result[lum>=155]=DEFAULT_PALETTE[1]
    out[ys,xs,:3]=result; out[ys,xs,3]=255
    return out

def normal_outline_palette(ref_dir):
    """Learn tex-edge RGB -> real normal-outline RGB from paired reference atlases."""
    src_samples=[]; dst_samples=[]; notes=[]
    if not ref_dir or not os.path.isdir(ref_dir):
        return None, None, '未使用法线参考样本；无法从 _tex 单独推断真实法线描边色谱'
    for fn in sorted(os.listdir(ref_dir)):
        if not fn.lower().endswith('_tex.png'):
            continue
        stem=fn[:-8]
        texp=os.path.join(ref_dir,fn)
        normal_candidates=[os.path.join(ref_dir,stem+'_normal.png'),os.path.join(ref_dir,stem+'_Normal.png'),os.path.join(ref_dir,stem+'_NORMAL.png')]
        mreo_candidates=[os.path.join(ref_dir,stem+'_mreo.png'),os.path.join(ref_dir,stem+'_mero.png')]
        npth=next((x for x in normal_candidates if os.path.isfile(x)),None)
        mp=next((x for x in mreo_candidates if os.path.isfile(x)),None)
        if not npth or not mp:
            continue
        try:
            tex=load_rgba(texp); normal=load_rgba(npth); mreo=load_rgba(mp)
            if tex.shape != normal.shape or tex.shape != mreo.shape:
                continue
            edge=outline_mask(tex[:,:,3])
            # Use confirmed outline locations from the paired _mreo map. The normal
            # baseline is (128,128,254); retain only actual non-flat normal colors.
            mask=edge & (mreo[:,:,3]>0)
            rgb=normal[:,:,:3].astype(np.int16)
            deviation=np.max(np.abs(rgb-np.array([128,128,254],dtype=np.int16)),axis=2)
            mask &= deviation >= 8
            if not mask.any():
                continue
            src_samples.append(tex[:,:,:3][mask].astype(np.uint8))
            dst_samples.append(normal[:,:,:3][mask].astype(np.uint8))
            notes.append(stem)
        except Exception:
            continue
    if not src_samples:
        return None,None,'未找到有效的 tex / mreo / normal 三件套参考样本'
    src_all=np.concatenate(src_samples); dst_all=np.concatenate(dst_samples)
    pairs=np.concatenate([src_all.astype(np.int16),dst_all.astype(np.int16)],axis=1)
    uniq,cnt=np.unique(pairs,axis=0,return_counts=True)
    mapping={}
    for rgb in np.unique(uniq[:,:3],axis=0):
        ix=np.all(uniq[:,:3]==rgb,axis=1)
        rows=uniq[ix]; counts=cnt[ix]
        keys=[tuple(map(int,row[3:])) for row in rows]
        totals={k:int(sum(counts[j] for j,v in enumerate(keys) if v==k)) for k in set(keys)}
        mapping[tuple(map(int,rgb))]=max(totals,key=totals.get)
    src=np.array(list(mapping.keys()),dtype=np.int16)
    dst=np.array(list(mapping.values()),dtype=np.uint8)
    return src,dst,'法线描边参考样本：'+', '.join(notes)+f'（学习到 {len(src)} 种边缘颜色）'


def find_paired_mreo(tex_path, ref_dir, out_dir=''):
    """Find paired _mreo/_mero; prefer output directory so generated mask is used."""
    stem=os.path.basename(tex_path)
    for suffix in ('_tex.png','_tex.PNG','_tex'):
        if stem.endswith(suffix): stem=stem[:-len(suffix)]; break
    folders=[]
    for folder in (out_dir, ref_dir, os.path.dirname(tex_path)):
        if folder and os.path.isdir(folder) and folder not in folders:
            folders.append(folder)
    for folder in folders:
        for name in (stem+'_mreo.png', stem+'_mero.png', stem+'_Mreo.png', stem+'_MERO.png'):
            path=os.path.join(folder,name)
            if os.path.isfile(path): return path
    return ''

def correct_normal(tex_path, normal_path, ref_dir, out_dir):
    """Use the paired generated _mreo alpha as the exact mask for Normal correction.

    Keep the NVIDIA normal RGB inside the _mreo alpha region; set all pixels
    outside it to flat normal (128,128,255). No color sampling, edge expansion,
    tex-alpha intersection, or height-removal processing is performed.
    """
    tex=load_rgba(tex_path)
    normal=load_rgba(normal_path)
    if tex.shape[:2] != normal.shape[:2]:
        raise ValueError(f'_tex and _normal dimensions differ: _tex={tex.shape[1]}x{tex.shape[0]}, _normal={normal.shape[1]}x{normal.shape[0]}')
    mreo_path=find_paired_mreo(tex_path, ref_dir, out_dir)
    if not mreo_path:
        raise FileNotFoundError('No matching _mreo.png / _mero.png found. Generate _mreo first and place it in the output folder, reference folder, or _tex folder.')
    mreo=load_rgba(mreo_path)
    if mreo.shape[:2] != tex.shape[:2]:
        raise ValueError(f'_mreo dimensions differ: {mreo.shape[1]}x{mreo.shape[0]}, expected {tex.shape[1]}x{tex.shape[0]}')
    mask=mreo[:,:,3] > 0
    out=normal.copy()
    # Equivalent to Normal layer 1 over a full-canvas flat-normal layer 2.
    # Pixels inside the mask retain the source Normal RGB; outside becomes flat normal.
    out[~mask,:3]=[128,128,255]
    out[:,:,3]=255
    stem=os.path.basename(tex_path)
    for suffix in ('_tex.png','_tex.PNG','_tex'):
        if stem.endswith(suffix): stem=stem[:-len(suffix)]; break
    os.makedirs(out_dir or os.path.dirname(normal_path) or '.',exist_ok=True)
    out_path=os.path.join(out_dir or os.path.dirname(normal_path) or '.',stem+'_Normal_Corrected.png')
    save_png(out,out_path)
    return out_path,int(mask.sum()),int((~mask).sum()),int((normal[:,:,3] < 255).sum()),f'Mask: {os.path.basename(mreo_path)} alpha', 'Normal RGB preserved inside _mreo alpha; outside filled with flat normal (128,128,255); output alpha set opaque to represent the full-canvas background layer'

def generate_mreo(tex_path, out_dir, ref_dir=''):
    """Generate an inner-outline _mreo using reference color mapping when available."""
    tex=load_rgba(tex_path)
    mask=outline_mask(tex[:,:,3], 'inner')
    src,dst,note=reference_palette(ref_dir)
    rgba=classify_outline_colors(tex[:,:,:3],mask,src,dst)
    os.makedirs(out_dir,exist_ok=True)
    stem=os.path.basename(tex_path)
    for suffix in ('_tex.png','_tex.PNG','_tex'):
        if stem.endswith(suffix):
            stem=stem[:-len(suffix)]
            break
    out_path=os.path.join(out_dir,stem+'_mreo.png')
    save_png(rgba,out_path)
    return out_path,int(mask.sum()),note

class App:
    TEXT={
      'zh': {
        'title':'FFRS 描边工具 v1.7','tex':'输入 _tex PNG','normal':'输入 _normal PNG','ref':'参考素材目录','out':'输出目录','choose':'选择…','lang':'语言',
        'description_title':'处理说明','description':'_normal制作方式：\n1.先用工具生成_mero，然后将_mero填充为白色/_tex填充为黑色，合并成黑底白边的一张贴图（用黑白模拟高度信息）；\n2.将黑底白边贴图导入NVIDIA Texture Tools Exporter，将Image Type改为Normal Map（空间设置随意）/Height Source选Alpha Channel/Height Generation拖至最大值，然后保存。\n注意：生成的法线贴图（normal map）的“描边”范围和_mero不一致，建议导入本工具，用修正normal描边收束范围。','description2':'',
        'gen':'生成 _mreo 描边','fix':'修正 Normal 描边','missing_tex':'请选择有效的 _tex PNG','missing_normal':'请选择 NVIDIA Texture Tools Exporter 生成的 _normal PNG','missing_ref':'请选择参考素材目录（用于生成 _mreo 时学习颜色）。','started_mreo':'开始生成 _mreo：','done':'处理完成','error':'处理失败','pixels':'描边像素：','output':'输出：','fixed':'修正完成','mask_pixels':'蒙板内像素：','outside_pixels':'已填充平坦法线像素：','mask_source':'蒙板来源：','alpha':'输入 Normal 透明像素数：','select_ref':'选择参考素材目录'
      },
      'en': {
        'title':'FFRS Outline Tool v1.7','tex':'Input _tex PNG','normal':'Input _normal PNG','ref':'Reference folder','out':'Output folder','choose':'Browse…','lang':'Language',
        'description_title':'Instructions','description':'How to create _normal:\n1. Generate _mero with this tool. Fill _mero with white and _tex with black, then combine them into one black image with a white outline (using black and white to simulate height information).\n2. Import the black-and-white image into NVIDIA Texture Tools Exporter. Set Image Type to Normal Map (any space setting is fine), set Height Source to Alpha Channel, drag Height Generation to the maximum, and save.\nNote: The outline range in the generated normal map may differ from _mero. Import it into this tool and use Correct Normal Outline to constrain the outline range.','description2':'',
        'gen':'Generate _mreo Outline','fix':'Correct Normal Outline','missing_tex':'Select a valid _tex PNG.','missing_normal':'Select the _normal PNG exported by NVIDIA Texture Tools Exporter.','missing_ref':'Select a reference folder (used to learn colors when generating _mreo).','started_mreo':'Generating _mreo: ','done':'Completed','error':'Processing failed','pixels':'Outline pixels: ','output':'Output: ','fixed':'Normal correction complete','mask_pixels':'Pixels inside mask: ','outside_pixels':'Pixels filled with flat normal: ','mask_source':'Mask source: ','alpha':'Transparent pixels in input Normal: ','select_ref':'Select reference folder'
      }
    }
    def __init__(self,root):
        self.root=root; self.lang=tk.StringVar(value=self._ui_lang()); self.vars={k:tk.StringVar() for k in ['tex','normal','out','ref']}
        self.load_settings()
        try:
            import kit.settings as _K
            self.lang.set(str((_K.load() or {}).get("ui_lang") or "zh"))
        except Exception:
            pass
        try:
            import kit.settings as _K
            self.vars['ref'].set(str(_K.input_psd()))
            self.vars['out'].set(str(_K.output_outlines()))
        except Exception:
            pass
        self.build(); self.update_language()
    @staticmethod
    def _ui_lang():
        try:
            import kit.settings as _K
            return str(_K.load().get("ui_lang") or "zh")
        except Exception:
            return "zh"

    def build(self):
        self.f=ttk.Frame(self.root,padding=14); self.f.pack(fill='both',expand=True); self.f.columnconfigure(1,weight=1); self.f.rowconfigure(7,weight=1)
        self.widgets={}
        HIDE_LANG = True   # 语言统一在 Toolkit 首页切换
        if not HIDE_LANG:
            self.widgets['lang_label']=ttk.Label(self.f); self.widgets['lang_label'].grid(row=0,column=2,sticky='e')
            self.lang_box=ttk.Combobox(self.f,textvariable=self.lang,values=['zh','en'],state='readonly',width=7)
            self.lang_box.grid(row=0,column=3,sticky='e')
            self.lang_box.bind('<<ComboboxSelected>>',lambda e:self.update_language())
        HIDE_PATHS = True   # 参考/输出统一由 Toolkit 首页决定
        rows=[('tex',1,self.scan_textures),('normal',2,self.scan_textures)]
        if not HIDE_PATHS:
            rows += [('ref',3,self.pick_ref),('out',4,self.pick_out)]
        for key,row,cmd in rows:
            self.widgets[key+'_label']=ttk.Label(self.f); self.widgets[key+'_label'].grid(row=row,column=0,sticky='w',pady=5)
            if key in ('tex','normal'):
                cb = ttk.Combobox(self.f, textvariable=self.vars[key], values=[], width=46, state="readonly")
                cb.grid(row=row,column=1,columnspan=2,sticky="ew",padx=8)
                self.widgets[key+'_combo'] = cb
            else:
                ttk.Entry(self.f,textvariable=self.vars[key]).grid(row=row,column=1,columnspan=2,sticky='ew',padx=8)
            self.widgets[key+'_button']=ttk.Button(self.f,command=cmd); self.widgets[key+'_button'].grid(row=row,column=3,sticky='ew')
        # 扫描统一输入目录里的贴图，供 tex/normal 下拉选择
        self.widgets['scan']=ttk.Button(self.f, text="扫描贴图", command=self.scan_textures)
        # 扫描按钮已下放到 tex/normal 行尾，这里不再显示
        ttk.Separator(self.f).grid(row=5,column=0,columnspan=4,sticky='ew',pady=8)
        self.widgets['desc_title']=ttk.Label(self.f,font=('TkDefaultFont',10,'bold')); self.widgets['desc_title'].grid(row=6,column=0,columnspan=4,sticky='w')
        self.widgets['desc']=ttk.Label(self.f,wraplength=760,justify='left'); self.widgets['desc'].grid(row=7,column=0,columnspan=4,sticky='new',pady=(5,2))
        self.widgets['desc2']=ttk.Label(self.f,wraplength=760,justify='left'); self.widgets['desc2'].grid(row=8,column=0,columnspan=4,sticky='new',pady=3)
        self.log=tk.Text(self.f,height=7,wrap='word'); self.log.grid(row=9,column=0,columnspan=4,sticky='nsew',pady=8); self.f.rowconfigure(9,weight=1)
        btns=ttk.Frame(self.f); btns.grid(row=10,column=0,columnspan=4,sticky='ew',pady=5); btns.columnconfigure(0,weight=1); btns.columnconfigure(1,weight=1)
        self.widgets['gen']=ttk.Button(btns,command=self.run_mreo); self.widgets['gen'].grid(row=0,column=0,sticky='ew',padx=(0,4))
        self.widgets['fix']=ttk.Button(btns,command=self.run_normal); self.widgets['fix'].grid(row=0,column=1,sticky='ew',padx=(4,0))
    def update_language(self):
        d=self.TEXT['en' if self.lang.get()=='en' else 'zh']; self.root.title(d['title'])
        if 'lang_label' in self.widgets: self.widgets['lang_label'].configure(text=d['lang'])
        if hasattr(self, 'lang_box'): self.lang_box.grid_remove()
        for key in ('tex','normal','ref','out'):
            if key+'_label' in self.widgets: self.widgets[key+'_label'].configure(text=d[key])
            if key+'_button' in self.widgets:
                self.widgets[key+'_button'].configure(
                    text=('扫描' if self.lang.get() != 'en' else 'Scan') if key in ('tex','normal') else d['choose'])
        self.widgets['desc_title'].configure(text=d['description_title']); self.widgets['desc'].configure(text=d['description']); self.widgets['desc2'].configure(text=d['description2'])
        self.widgets['gen'].configure(text=d['gen']); self.widgets['fix'].configure(text=d['fix'])
    def scan_textures(self, *_):
        """扫描统一输入目录（<输入>/SpritePSD），把 png 填进 tex/normal 下拉。"""
        from pathlib import Path
        try:
            import kit.settings as _K
            root = _K.input_psd()
        except Exception:
            root = Path(".")
        files = []
        try:
            for p in sorted(root.rglob("*.png")):
                files.append(str(p))
                if len(files) >= 400:
                    break
        except Exception:
            pass
        for key in ("tex", "normal"):
            cb = self.widgets.get(key + "_combo")
            if cb is not None:
                cb.configure(values=files)
        try:
            import kit.settings as _K
            self.vars['ref'].set(str(_K.input_psd()))
            self.vars['out'].set(str(_K.output_outlines()))
        except Exception:
            pass
        self.say(f"扫描到 {len(files)} 个 PNG：{root}")

    def pick_tex(self):
        p=filedialog.askopenfilename(filetypes=[('PNG','*.png'),('All files','*.*')])
        if p:
            self.vars['tex'].set(p)
            if not self.vars['out'].get(): self.vars['out'].set(os.path.dirname(p))
            if not self.vars['ref'].get(): self.vars['ref'].set(os.path.dirname(p))
    def pick_normal(self):
        p=filedialog.askopenfilename(filetypes=[('PNG','*.png'),('All files','*.*')])
        if p:self.vars['normal'].set(p)
    def pick_out(self):
        p=filedialog.askdirectory()
        if p:self.vars['out'].set(p)
    def pick_ref(self):
        p=filedialog.askdirectory()
        if p:self.vars['ref'].set(p)
    def say(self,s):
        try:
            import kit.i18n as _I
            s = _I.tr_log(str(s))
        except Exception:
            pass
        self.log.insert('end',s+'\n'); self.log.see('end')
    def run_mreo(self):
        d=self.TEXT['en' if self.lang.get()=='en' else 'zh']; tex=self.vars['tex'].get().strip(); out=self.vars['out'].get().strip() or (os.path.dirname(tex) if tex else ''); ref=self.vars['ref'].get().strip()
        if not os.path.isfile(tex): messagebox.showerror(d['error'],d['missing_tex']); return
        self.save_settings(); self.say(d['started_mreo']+tex)
        try:
            path,count,note=generate_mreo(tex,out,ref); self.say(note); self.say(d['pixels']+str(count)); self.say(d['output']+path)
            messagebox.showinfo(d['done'],d['output']+'\n'+path+'\n'+d['pixels']+str(count))
        except Exception as e:
            self.say(d['error']+': '+repr(e)); messagebox.showerror(d['error'],str(e))
    def run_normal(self):
        d=self.TEXT['en' if self.lang.get()=='en' else 'zh']; tex=self.vars['tex'].get().strip(); normal=self.vars['normal'].get().strip(); out=self.vars['out'].get().strip() or (os.path.dirname(tex) if tex else ''); ref=self.vars['ref'].get().strip()
        if not os.path.isfile(tex): messagebox.showerror(d['error'],d['missing_tex']); return
        if not os.path.isfile(normal): messagebox.showerror(d['error'],d['missing_normal']); return
        self.save_settings(); self.say('Correcting Normal: '+normal)
        try:
            path,kept,cleared,transparent,mask_note,alpha_note=correct_normal(tex,normal,ref,out)
            self.say(mask_note); self.say(alpha_note); self.say(d['mask_pixels']+str(kept)); self.say(d['outside_pixels']+str(cleared)); self.say(d['output']+path)
            messagebox.showinfo(d['fixed'],d['output']+'\n'+path+'\n\n'+d['mask_pixels']+str(kept)+'\n'+d['outside_pixels']+str(cleared))
        except Exception as e:
            self.say(d['error']+': '+repr(e)); messagebox.showerror(d['error'],str(e))
    def load_settings(self):
        try:
            with open(SETTINGS,'r',encoding='utf-8') as f: data=json.load(f)
            for k,v in data.items():
                if k in self.vars:self.vars[k].set(str(v))
            if data.get('language') in ('zh','en'): self.lang.set(data['language'])
        except Exception: pass
    def save_settings(self):
        try:
            data={k:v.get() for k,v in self.vars.items()}; data['language']=self.lang.get()
            with open(SETTINGS,'w',encoding='utf-8') as f: json.dump(data,f,ensure_ascii=False,indent=2)
        except Exception: pass

if __name__=='__main__':
    root=tk.Tk(); App(root); root.mainloop()
