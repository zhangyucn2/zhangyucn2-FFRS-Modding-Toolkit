#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FFRS Sprite <-> PSD Tool v1.1

Integrated practical build based on the validated FFRS / SpriteStudio research.

Features
--------
- Parse UE5 .uasset/.uexp resources. .uexp remains authoritative for animation.
- Accept a resource when .uasset + .uexp + any of _tex/_normal/_mreo exists.
- _tex is the preview texture; companion textures share the same Cell geometry.
- Full animation preview using Parent Matrix + Cell Pivot + nearest rasterization.
- Export the selected animation to both Standard PSD and Safe 1px PSD.
- Optional export for all available texture variants.
- PSD -> Sprite recovery independent of Photoshop layer stack order.
- Safe 1px border is automatically stripped during recovery.
- Layer identity comes from Animation Group + Frame Group + Part/Cell layer name.
- Shared Cell edits are merged only when all mapped instances agree; conflicts are reported.
- Existing Cell crop export/recovery from the original Analyzer remains available.
"""
from __future__ import annotations
import json, traceback, shutil, re, struct, math
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageTk

import sys
try:
    HERE = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
except Exception:
    HERE = Path(__file__).resolve().parent
import FFRS_SpritePSD_Tool_v1_1_core as core
from v3inspect import transform_eval as te

APP_VERSION="1.1.24"
SETTINGS_NAME="FFRS_SpritePSD_Tool_settings.json"
SETTINGS_DIR=HERE
try:
    import kit.settings as _KIT
    SETTINGS_DIR = _KIT.CONFIG_DIR          # ← 必须是 config/ 本身，不是它的父目录
except Exception:
    pass

ZH={
    "title":"FFRS Sprite ↔ PSD Tool v1.1",
    "heading":"FFRS Sprite ↔ PSD Tool v1.1",
    "subtitle":"基于逆向坐标的 Sprite / PSD 互转与动画预览",
    "input":"输入目录","resource":"角色资源","output":"输出目录","choose":"选择...","scan":"扫描",
    "parse":"解析 / 刷新预览","export_psd":"导出当前动画 PSD（标准 + Safe 1px + 编号版）","export_frame_psd":"导出当前帧 PSD","export_resource_psd":"导出角色资源 PSD（全部切片）","export_crops":"导出切片（_tex / _normal / _mreo）",
    "recover":"从 PSD 还原 Sprite（全部切片 / 当前动画）","atlas":"原始精灵片 / Atlas","psd":"修改后的 PSD","outpng":"还原输出目录",
    "texture":"PSD 导出贴图","tex":"_tex（预览）","alltex":"所有可用贴图","normal":"_normal","mreo":"_mreo",
    "animations":"动画","preview":"动画预览","frame":"帧","play":"播放","pause":"暂停","gif":"导出 GIF","speed":"播放速度",
    "layers":"当前帧图层","info":"帧信息","idle":"等待解析。","scan_first":"请先选择输入目录并扫描角色资源。",
    "no_resource":"没有找到可用的 .uasset + .uexp + 纹理资源。","parse_start":"正在直接读取 UEXP 动画数据…",
    "parse_done":"解析完成：{a} 个动画，{p} 个 Part。",
    "export_done":"PSD 导出完成，共生成 {n} 个 PSD 文件。",
    "unlink_refs":"解除引用 / 隐藏区间（按编号）",
    "recover_done":"Recovery 完成：修改 {c} 个源像素。",
    "recover_conflict":"Recovery 已停止合并冲突像素：{n} 处冲突。请检查报告。",
    "need_parse":"请先解析资源。","need_psd":"请选择修改后的 PSD。","need_atlas":"请选择原始 Atlas。","need_output":"请选择输出目录。",
    "existing":"输出目录已有同名结果。继续会覆盖同名文件，是否继续？",
    "safe_note":"Safe 1px：每个 PSD 图层四周增加 1px 实体安全框，Recovery 时自动剥离。",
    "identity_note":"Recovery 不依赖 PSD 图层上下顺序；只识别动画 Group、Frame Group 与 Part/Cell 图层身份。",
}
EN={
    "title":"FFRS Sprite ↔ PSD Tool v1.1","heading":"FFRS Sprite ↔ PSD Tool v1.1","subtitle":"Sprite / PSD round-trip and animation preview driven by reverse-engineered coordinates",
    "input":"Input directory","resource":"Character resource","output":"Output directory","choose":"Choose...","scan":"Scan",
    "parse":"Parse / Refresh Preview","export_psd":"Export Current Animation PSD (Standard + Safe 1px + Numbered)","export_frame_psd":"Export Current Frame PSD","export_resource_psd":"Export Character Resource PSD (All Cells)","export_crops":"Export Texture Crops (_tex / _normal / _mreo)",
    "recover":"Recover Sprite from PSD (All Cells / Current Animation)","atlas":"Original Sprite / Atlas","psd":"Modified PSD","outpng":"Recovery output folder",
    "texture":"PSD export texture","tex":"_tex (preview)","alltex":"All available textures","normal":"_normal","mreo":"_mreo",
    "animations":"Animations","preview":"Animation preview","frame":"Frame","play":"Play","pause":"Pause","gif":"Export GIF","speed":"Speed",
    "layers":"Layers in current frame","info":"Frame info","idle":"Ready.","scan_first":"Choose an input directory and scan resources first.",
    "no_resource":"No usable .uasset + .uexp + texture resource found.","parse_start":"Reading UEXP animation data directly…",
    "parse_done":"Parsed: {a} animations, {p} Parts.","export_done":"PSD export finished: {n} PSD files created.",
    "unlink_refs":"Unlink / hide range by Cell number",
    "recover_done":"Recovery finished: {c} source pixels modified.","recover_conflict":"Recovery stopped on conflicting source pixels: {n}. Check the report.",
    "need_parse":"Parse the resource first.","need_psd":"Choose the modified PSD.","need_atlas":"Choose the original Atlas.","need_output":"Choose an output folder.",
    "existing":"The output directory already contains matching results. Continue and overwrite same-name files?",
    "safe_note":"Safe 1px: every PSD layer gets a solid 1px border on all four sides; Recovery strips it automatically.",
    "identity_note":"Recovery does not depend on PSD layer stack order; only Animation Group, Frame Group, and Part/Cell layer identity are used.",
}

from kit.host import WindowMixin

class App(WindowMixin, tk.Frame):
    HIDE_LANG = True     # 语言统一在 Toolkit 首页切换
    HIDE_IO = True       # 输入/输出目录统一在首页设置（角色资源不是输入，保留）
    def __init__(self, master=None):
        self._bind_window(master)
        self.lang="zh"
        self.vars={k:tk.StringVar() for k in ["input","resource","output","atlas","psd","outpng"]}
        self.resource=None; self.data=None; self.animation_names=[]; self.animation=None; self.current_anim_name=""; self.frame=0
        self._recorded_frame_edits={}  # (resource_path, animation, frame, part_index) -> screen-space delta
        self.playing=False; self.after_id=None; self.preview_img=None; self.preview_zoom=1.0; self.preview_offset_x=0; self.preview_offset_y=0; self._preview_drag=None
        self.speed=tk.StringVar(value="0.5x"); self.texture_mode=tk.StringVar(value="all")
        self.build_ui(); self.load_settings(); self.apply_lang(); self.protocol("WM_DELETE_WINDOW",self.close)
        try:
            import kit.settings as _K0
            if not self.vars["outpng"].get():
                self.vars["outpng"].set(str(_K0.output_psd() / "recover"))
            if not self.vars["output"].get():
                self.vars["output"].set(str(_K0.output_psd()))
        except Exception:
            pass

    def T(self,k,**kw):
        d=ZH if self.lang=="zh" else EN
        return d[k].format(**kw)

    def build_ui(self):
        self.geometry("1280x860"); self.minsize(1050,720)
        self.columnconfigure(0,weight=1); self.rowconfigure(4,weight=1)
        top=ttk.Frame(self,padding=(12,10,12,6)); top.grid(row=0,column=0,sticky="ew"); top.columnconfigure(1,weight=1)
        self.heading=ttk.Label(top,font=("Segoe UI",16,"bold")); self.heading.grid(row=0,column=0,sticky="w")
        if not self.HIDE_LANG:
            self.lang_box=ttk.Combobox(top,state="readonly",values=["中文","English"],width=10); self.lang_box.grid(row=0,column=2,padx=(10,0)); self.lang_box.bind("<<ComboboxSelected>>",self.lang_changed)
        self.subtitle=ttk.Label(top); self.subtitle.grid(row=1,column=0,columnspan=3,sticky="w",pady=(3,0))

        form=ttk.Frame(self,padding=(12,0,12,5)); form.grid(row=1,column=0,sticky="ew"); form.columnconfigure(1,weight=1)
        self.labels={}; self.buttons={}
        for i,k in enumerate(["resource"] if self.HIDE_IO else ["input","resource","output"]):
            self.labels[k]=ttk.Label(form); self.labels[k].grid(row=i,column=0,sticky="w",padx=(0,8),pady=(0,5))
            if k=="resource":
                w=ttk.Combobox(form,state="readonly"); w.grid(row=i,column=1,sticky="ew",pady=(0,5)); w.bind("<<ComboboxSelected>>",self.resource_changed); self.resource_box=w
                b=ttk.Button(form,command=self.scan)
            else:
                w=ttk.Entry(form,textvariable=self.vars[k]); w.grid(row=i,column=1,sticky="ew",pady=(0,5)); b=ttk.Button(form,command=lambda kk=k:self.pick_dir(kk))
            b.grid(row=i,column=2,sticky="e",padx=(8,0),pady=(0,5)); self.buttons[k]=b

        note=ttk.Label(self,padding=(12,2)); note.grid(row=2,column=0,sticky="ew"); self.note=note

        ops=ttk.Frame(self,padding=(12,4,12,6)); ops.grid(row=3,column=0,sticky="ew"); ops.columnconfigure(1,weight=1)
        self.parse_btn=ttk.Button(ops,command=self.parse_resource); self.parse_btn.grid(row=0,column=0,padx=(0,6),sticky="w")
        self.export_psd_btn=ttk.Button(ops,command=self.export_psd); self.export_psd_btn.grid(row=0,column=1,padx=(0,6),sticky="w")
        self.export_frame_psd_btn=ttk.Button(ops,command=self.export_frame_psd); self.export_frame_psd_btn.grid(row=0,column=2,padx=(0,6),sticky="w")
        self.export_resource_psd_btn=ttk.Button(ops,command=self.export_resource_psd); self.export_resource_psd_btn.grid(row=0,column=3,padx=(0,6),sticky="w")
        self.export_crop_btn=ttk.Button(ops,command=self.export_crops); self.export_crop_btn.grid(row=0,column=4,sticky="w")
        ops.columnconfigure(4,weight=1)
        self.check_psd_btn=ttk.Button(ops,command=self.check_psd); self.check_psd_btn.grid(row=0,column=5,padx=(6,3),sticky="e")
        self.compare_psd_btn=ttk.Button(ops,command=self.compare_psd_layers); self.compare_psd_btn.grid(row=0,column=6,padx=(3,6),sticky="e")
        self.recover_btn=ttk.Button(ops,command=self.recover_psd); self.recover_btn.grid(row=0,column=7,sticky="e")
        self.find_cell_refs_btn=ttk.Button(ops,command=self.open_find_cell_refs); self.find_cell_refs_btn.grid(row=1,column=0,pady=(6,0),padx=(0,6),sticky="w")
        self.unlink_refs_btn=ttk.Button(ops,command=self.open_unlink_refs); self.unlink_refs_btn.grid(row=1,column=1,pady=(6,0),sticky="w")
        self.edit_frame_btn=ttk.Button(ops,command=self.open_frame_editor); self.edit_frame_btn.grid(row=1,column=2,pady=(6,0),padx=(6,0),sticky="w")
        self.save_frames_btn=ttk.Button(ops,command=self.save_recorded_animation_frames); self.save_frames_btn.grid(row=1,column=3,pady=(6,0),padx=(6,0),sticky="w")

        pane=ttk.Panedwindow(self,orient="horizontal"); pane.grid(row=4,column=0,sticky="nsew",padx=10,pady=4)
        left=ttk.Frame(pane,padding=6); mid=ttk.Frame(pane,padding=6); right=ttk.Frame(pane,padding=6)
        pane.add(left,weight=2); pane.add(mid,weight=5); pane.add(right,weight=2)
        self.anim_label=ttk.Label(left); self.anim_label.pack(anchor="w")
        self.anim_box=ttk.Combobox(left,state="readonly"); self.anim_box.pack(fill="x",pady=5); self.anim_box.bind("<<ComboboxSelected>>",self.animation_changed)
        self.anim_list=tk.Listbox(left,exportselection=False); self.anim_list.pack(fill="both",expand=True); self.anim_list.bind("<<ListboxSelect>>",self.list_animation_changed)

        self.preview_label=ttk.Label(mid); self.preview_label.pack(anchor="w")
        self.canvas=tk.Canvas(mid,bg="#202020",highlightthickness=0); self.canvas.pack(fill="both",expand=True,pady=5); self.canvas.bind("<Configure>",lambda e:self.draw_preview())
        # Mouse-wheel zoom for the animation preview (Windows/macOS and Linux).
        self.canvas.bind("<MouseWheel>",self.preview_mousewheel)
        self.canvas.bind("<Button-4>",lambda e:self.change_preview_zoom(1))
        self.canvas.bind("<Button-5>",lambda e:self.change_preview_zoom(-1))
        self.canvas.bind("<Enter>",lambda e:self.canvas.focus_set())
        # Left-button drag pans the preview when zoomed (and also works at normal scale).
        self.canvas.bind("<ButtonPress-1>",self.preview_drag_start)
        self.canvas.bind("<B1-Motion>",self.preview_drag_motion)
        self.canvas.bind("<ButtonRelease-1>",self.preview_drag_end)
        ctl=ttk.Frame(mid); ctl.pack(fill="x")
        self.play_btn=ttk.Button(ctl,command=self.toggle_play); self.play_btn.pack(side="left")
        self.prev_btn=ttk.Button(ctl,text="◀",width=4,command=lambda:self.step(-1)); self.prev_btn.pack(side="left",padx=3)
        self.next_btn=ttk.Button(ctl,text="▶",width=4,command=lambda:self.step(1)); self.next_btn.pack(side="left",padx=3)
        self.frame_label=ttk.Label(ctl); self.frame_label.pack(side="left",padx=(12,4))
        self.frame_scale=tk.Scale(ctl,from_=0,to=0,orient="horizontal",showvalue=False,command=self.scale_changed,length=360); self.frame_scale.pack(side="left",fill="x",expand=True)
        ttk.Label(ctl,text="").pack(side="left",padx=2)
        self.speed_box=ttk.Combobox(ctl,state="readonly",textvariable=self.speed,values=["0.25x","0.5x","0.75x","1x","1.5x","2x"],width=7); self.speed_box.pack(side="right")
        self.speed_box.bind("<<ComboboxSelected>>",lambda e:self.save_settings())
        self.gif_btn=ttk.Button(ctl,command=self.export_gif); self.gif_btn.pack(side="right",padx=(8,0))

        self.layers_label=ttk.Label(right); self.layers_label.pack(anchor="w")
        self.layer_list=tk.Listbox(right,exportselection=False); self.layer_list.pack(fill="both",expand=True,pady=5); self.layer_list.bind("<<ListboxSelect>>",self.layer_selected)
        self.info_box=ttk.LabelFrame(right); self.info_box.pack(fill="x")
        self.info=tk.Text(self.info_box,height=12,wrap="word"); self.info.pack(fill="both",expand=True)

        self.status=tk.StringVar(value=""); ttk.Label(self,textvariable=self.status,anchor="w").grid(row=5,column=0,sticky="ew",padx=12,pady=4)

        # Recovery controls are kept compactly in a collapsible-ish bottom strip.
        rec=ttk.LabelFrame(self,padding=(8,6)); rec.grid(row=6,column=0,sticky="ew",padx=12,pady=(0,8)); rec.columnconfigure(1,weight=1); rec.columnconfigure(4,weight=1)
        # 原始精灵片 / 修改后 PSD：扫描 <输入>/SpritePSD 后下拉选择（输出统一到首页 Output/SpritePSD）
        self.r_atlas=ttk.Label(rec); self.r_atlas.grid(row=0,column=0,sticky="w",padx=(0,6))
        self.atlas_box=ttk.Combobox(rec,state="readonly",textvariable=self.vars["atlas"],values=[])
        self.atlas_box.grid(row=0,column=1,sticky="ew")
        self.atlas_btn=ttk.Button(rec,text="扫描",width=6,command=self.scan_recover_lists)
        self.atlas_btn.grid(row=0,column=2,padx=(6,10))
        self.r_psd=ttk.Label(rec); self.r_psd.grid(row=0,column=3,sticky="w",padx=(0,6))
        self.psd_box=ttk.Combobox(rec,state="readonly",textvariable=self.vars["psd"],values=[])
        self.psd_box.grid(row=0,column=4,sticky="ew")
        self.psd_btn=ttk.Button(rec,text="扫描",width=6,command=self.scan_recover_lists)
        self.psd_btn.grid(row=0,column=5,padx=(6,10))
        self.r_out=None
        self.texture_label=ttk.Label(rec); self.texture_label.grid(row=2,column=0,sticky="w",pady=(4,0))
        self.texture_box=ttk.Combobox(rec,state="readonly",textvariable=self.texture_mode,values=["tex","all","normal","mreo"],width=16); self.texture_box.grid(row=2,column=1,sticky="w",pady=(4,0))

    def apply_lang(self):
        self.title(self.T("title"))
        try:
            self.heading.grid_remove()      # 顶部工具名统一由 Toolkit 标签显示
        except Exception:
            pass
        self.subtitle.config(text=self.T("subtitle"))
        for k,l in self.labels.items(): l.config(text=self.T(k))
        for k, key in (("input", "choose"), ("output", "choose"), ("resource", "scan")):
            if k in getattr(self, "buttons", {}):
                self.buttons[k].config(text=self.T(key))
        self.parse_btn.config(text=self.T("parse")); self.note.config(text=self.T("safe_note")+"  "+self.T("identity_note"))
        self.export_psd_btn.config(text=self.T("export_psd")); self.export_frame_psd_btn.config(text=self.T("export_frame_psd")); self.export_resource_psd_btn.config(text=self.T("export_resource_psd")); self.export_crop_btn.config(text=self.T("export_crops")); self.recover_btn.config(text=self.T("recover")); self.check_psd_btn.config(text="检查 PSD 图层" if self.lang=="zh" else "Check PSD Layers"); self.compare_psd_btn.config(text="对比 PSD 图层" if self.lang=="zh" else "Compare PSD Layers"); self.unlink_refs_btn.config(text=self.T("unlink_refs")); self.edit_frame_btn.config(text="编辑动画帧" if self.lang=="zh" else "Edit Animation Frame"); self.save_frames_btn.config(text="保存动画帧" if self.lang=="zh" else "Save Animation Frames"); self.find_cell_refs_btn.config(text="检索切片动画引用" if self.lang=="zh" else "Find Cell Animation References")
        self.anim_label.config(text=self.T("animations")); self.preview_label.config(text=self.T("preview")); self.layers_label.config(text=self.T("layers")); self.info_box.config(text=self.T("info")); self.play_btn.config(text=self.T("pause") if self.playing else self.T("play")); self.gif_btn.config(text=self.T("gif"))
        self.r_atlas.config(text=self.T("atlas")); self.r_psd.config(text=self.T("psd")); self.texture_label.config(text=self.T("texture"))
        for b in (getattr(self, "atlas_btn", None), getattr(self, "psd_btn", None)):
            if b is not None: b.config(text="扫描" if self.lang == "zh" else "Scan")
        if hasattr(self, "lang_box"): self.lang_box.set("中文" if self.lang=="zh" else "English")
        self.status.set(self.status.get() or self.T("idle"))
        self.update_texture_labels()

    def lang_changed(self,_=None): self.lang="zh" if self.lang_box.get()=="中文" else "en"; self.apply_lang(); self.save_settings()
    def scan_recover_lists(self):
        """扫描 <输入>/SpritePSD 下的 png，填进 原始精灵片 / 修改后 PSD 两个下拉。"""
        from pathlib import Path as _P
        root = _P(self._default_input() or ".")
        pngs, layers = [], []
        try:
            pngs = [str(p) for p in sorted(root.rglob("*.png"))][:800]
        except Exception:
            pass
        for ext in ("*.psd", "*.tif", "*.tiff", "*.psb"):
            try:
                layers += [str(p) for p in sorted(root.rglob(ext))][:800]
            except Exception:
                pass
        if getattr(self, "atlas_box", None) is not None:
            self.atlas_box.configure(values=pngs)
        if getattr(self, "psd_box", None) is not None:
            self.psd_box.configure(values=layers)
        self.status.set(f"扫描：精灵片 {len(pngs)} 个 / 可编辑图层文件 {len(layers)} 个（{root}）")

    def pick_dir(self,k):
        p=filedialog.askdirectory()
        if p: self.vars[k].set(p); self.scan() if k=="input" else None; self.save_settings()
    def _default_input(self):
        try:
            import kit.settings as _K
            return str(_K.input_psd())
        except Exception:
            return ""

    def scan(self):
        root=Path(self.vars["input"].get().strip() or self._default_input())
        if not root.exists(): self.status.set(self.T("scan_first")); return
        root.mkdir(exist_ok=True); (root/"char").mkdir(exist_ok=True); (root/"other").mkdir(exist_ok=True)
        try: self.resource_list=core.ssa.discover_resources(root,"char")
        except Exception:
            self.resource_list=[]
        names=[r.stem for r in self.resource_list]; self.resource_box["values"]=names
        if names:
            idx=names.index(self.vars["resource"].get()) if self.vars["resource"].get() in names else 0
            self.resource_box.current(idx); self.resource=self.resource_list[idx]; self.vars["resource"].set(names[idx])
            if not self.vars["output"].get():
                try:
                    import kit.settings as _K
                    self.vars["output"].set(str(_K.output_psd()))
                except Exception:
                    self.vars["output"].set(str(root/"analysis"))
            self.status.set(f"char={len(names)} | {self.resource.stem}: "+", ".join(k for k,v in self.resource.textures().items() if v))
        else:
            self.resource=None; self.resource_box.set(""); self.status.set(self.T("no_resource"))

    def resource_changed(self,_=None):
        idx=self.resource_box.current()
        if idx>=0 and idx<len(self.resource_list):
            self.resource=self.resource_list[idx]; self.vars["resource"].set(self.resource.stem); self.data=None; self.clear_preview(); self.status.set(self.resource.stem)

    def parse_resource(self):
        try:
            if self.resource is None:
                self.scan()
            if self.resource is None: raise FileNotFoundError(self.T("no_resource"))
            self.status.set(self.T("parse_start")); self.update_idletasks()
            self.data=core.load_resource(self.resource)
            self.animation_names=[a["name"] for a in self.data["animations"] if a.get("header_type")!="Setup" and a.get("frame_count")]
            self.anim_box["values"]=self.animation_names; self.anim_list.delete(0,"end")
            for n in self.animation_names: self.anim_list.insert("end",n)
            if self.animation_names:
                self.anim_box.current(0); self.anim_list.selection_set(0); self.set_animation(self.animation_names[0])
            self.status.set(self.T("parse_done",a=len(self.animation_names),p=sum(a.get("part_count",0) for a in self.data["animations"])))
            # Initialize recovery Atlas only when unset. Parse / Refresh Preview
            # must never overwrite a user-selected recovery source path.
            if not self.vars["atlas"].get().strip():
                default_atlas = self.resource.tex or self.resource.normal or self.resource.mreo
                if default_atlas: self.vars["atlas"].set(str(default_atlas))
            self.save_settings()
        except Exception as e:
            traceback.print_exc(); self.status.set(str(e)); messagebox.showerror(self.T("title"),str(e))

    def set_animation(self,name):
        if not self.data: return
        try:
            self.animation=core.animation_by_name(self.data,name); self.current_anim_name=name; self.frame=0
            total=max(0,int(self.animation.get("frame_count") or 0)-1); self.frame_scale.config(to=total); self.frame_scale.set(0)
            self.draw_preview()
        except Exception as e: self.status.set(str(e))
    def animation_changed(self,_=None): self.set_animation(self.anim_box.get())
    def list_animation_changed(self,_=None):
        s=self.anim_list.curselection()
        if s and s[0]<len(self.animation_names): self.anim_box.current(s[0]); self.set_animation(self.animation_names[s[0]])

    def scale_changed(self,v):
        if not self.animation: return
        self.frame=int(round(float(v))); self.draw_preview()
    def step(self,d):
        if not self.animation or not self.animation.get("frame_count"): return
        self.frame=(self.frame+d)%int(self.animation["frame_count"]); self.frame_scale.set(self.frame); self.draw_preview()
    def toggle_play(self):
        if not self.animation: return
        self.playing=not self.playing; self.play_btn.config(text=self.T("pause") if self.playing else self.T("play"))
        if self.playing: self.tick()
        elif self.after_id: self.after_cancel(self.after_id); self.after_id=None
    def tick(self):
        if not self.playing: return
        self.step(1); factor={"0.25x":4.0,"0.5x":2.0,"0.75x":1.333333,"1x":1.0,"1.5x":0.666667,"2x":0.5}.get(self.speed.get(),2.0)
        fps=max(1,int(self.animation.get("fps") or 30)); delay=max(30,int(1000/fps*factor)); self.after_id=self.after(delay,self.tick)

    def preview_mousewheel(self,event):
        delta = getattr(event, "delta", 0)
        if delta:
            self.change_preview_zoom(1 if delta > 0 else -1)
        return "break"

    def preview_drag_start(self,event):
        self._preview_drag=(event.x,event.y,self.preview_offset_x,self.preview_offset_y)
        return "break"

    def preview_drag_motion(self,event):
        if self._preview_drag is None:
            return "break"
        start_x,start_y,offset_x,offset_y=self._preview_drag
        new_x=offset_x+(event.x-start_x)
        new_y=offset_y+(event.y-start_y)
        dx=new_x-self.preview_offset_x
        dy=new_y-self.preview_offset_y
        if dx or dy:
            self.canvas.move("preview_image",dx,dy)
            self.preview_offset_x=new_x
            self.preview_offset_y=new_y
        return "break"

    def preview_drag_end(self,event=None):
        self._preview_drag=None
        return "break"

    def change_preview_zoom(self,direction):
        old=self.preview_zoom
        self.preview_zoom=max(0.1,min(8.0,old*(1.15 if direction>0 else 1/1.15)))
        if abs(old-self.preview_zoom)>1e-9:
            self.draw_preview()
            pct=int(round(self.preview_zoom*100))
            self.status.set(("预览缩放：%d%%（滚轮可调整）" if self.lang=="zh" else "Preview zoom: %d%% (use mouse wheel)") % pct)

    def draw_preview(self):
        self.canvas.delete("all")
        if not self.resource or not self.data or not self.animation or not self.resource.tex:
            return
        try:
            image,info=core.render_animation_frame(self.resource,self.data,self.current_anim_name,self.frame,"tex")
            maxw=max(64,self.canvas.winfo_width()-20); maxh=max(64,self.canvas.winfo_height()-20)
            if image.width and image.height:
                sc=min(maxw/image.width,maxh/image.height,4.0)*self.preview_zoom; size=(max(1,int(image.width*sc)),max(1,int(image.height*sc)))
                self.preview_img=ImageTk.PhotoImage(image.resize(size,Image.Resampling.NEAREST)); self.canvas.create_image(self.canvas.winfo_width()//2+self.preview_offset_x,self.canvas.winfo_height()//2+self.preview_offset_y,image=self.preview_img,anchor="center",tags=("preview_image",))
            self.layer_list.delete(0,"end")
            for r in info["layers"]:
                self.layer_list.insert("end",f"Part_{r.part_index:03d}  Cell_{r.cell_id}  {r.part_name}")
            self.frame_label.config(text=f"{self.T('frame')}: {self.frame}/{max(0,int(self.animation['frame_count'])-1)}  | FPS {self.animation.get('fps',30)}")
            self.write_info(info)
        except Exception as e:
            self.canvas.create_text(max(20,self.canvas.winfo_width()//2),max(20,self.canvas.winfo_height()//2),text=str(e),fill="orange")
    def layer_selected(self,_=None):
        if not self.data or not self.animation: return
        s=self.layer_list.curselection()
        if not s: return
        try:
            _,info=core.render_animation_frame(self.resource,self.data,self.current_anim_name,self.frame,"tex")
            r=info["layers"][s[0]]; self.info.delete("1.0","end"); self.info.insert("end",json.dumps({"part":r.part_index,"name":r.part_name,"cell":r.cell_id,"node":[r.node_id,r.parent_id],"atlas":r.atlas_rect,"bbox":r.bbox,"local":r.local,"world_matrix":list(r.world_matrix)},ensure_ascii=False,indent=2))
        except Exception: pass
    def write_info(self,info):
        self.info.delete("1.0","end"); self.info.insert("end",json.dumps({"animation":info["animation"],"frame":info["frame"],"canvas":info["canvas"],"sort_mode":info["sort_mode"],"layers":info["layer_count"]},ensure_ascii=False,indent=2))

    def available_texture_kinds(self):
        if not self.resource: return []
        return [k for k,p in self.resource.textures().items() if p]
    def update_texture_labels(self):
        if self.texture_mode.get()=="tex": self.texture_mode.set("tex")
        elif self.texture_mode.get() not in ["tex","all","normal","mreo"]: self.texture_mode.set("all")
    def selected_kinds(self):
        av=self.available_texture_kinds()
        m=self.texture_mode.get()
        if m=="all": return av
        return [m] if m in av else (["tex"] if "tex" in av else av[:1])

    def export_psd(self):
        try:
            if not self.data or not self.animation: raise RuntimeError(self.T("need_parse"))
            out=Path(self.vars["output"].get().strip())
            if not out: raise RuntimeError(self.T("need_output"))
            dest=out/self.resource.stem/"psd"/core.safe_name(self.current_anim_name)
            if dest.exists() and any(dest.iterdir()):
                if not messagebox.askyesno(self.T("title"),self.T("existing"),default=messagebox.YES): return
            count=0
            for kind in self.selected_kinds():
                for safe,numbered in ((False,False),(True,False),(False,True)):
                    outputs=core.export_animation_psd(self.resource,self.data,self.current_anim_name,dest,kind,safe,numbered=numbered)
                    count+=len(outputs)
            afs=core.unique_animation_frames(self.animation,self.data)
            self.status.set(self.T("export_done",n=count)); messagebox.showinfo(self.T("title"),self.status.get()+f"\nAnimationFrame: {len(afs)} / timeline frames: {int(self.animation.get('frame_count') or 0)}\n\n"+str(dest))
        except Exception as e:
            traceback.print_exc(); messagebox.showerror(self.T("title"),str(e))

    def export_frame_psd(self):
        """Export only the timeline frame currently selected in the preview."""
        try:
            if not self.data or not self.animation or not self.resource:
                raise RuntimeError(self.T("need_parse"))
            out_text=self.vars["output"].get().strip()
            if not out_text: raise RuntimeError(self.T("need_output"))
            frame=max(0,min(int(self.frame),int(self.animation.get("frame_count") or 1)-1))
            dest=Path(out_text)/self.resource.stem/"frame_psd"/core.safe_name(self.current_anim_name)/f"frame_{frame:04d}"
            if dest.exists() and any(dest.iterdir()):
                if not messagebox.askyesno(self.T("title"),self.T("existing"),default=messagebox.YES): return
            dest.mkdir(parents=True,exist_ok=True)
            outputs=[]
            for kind in self.selected_kinds():
                for safe,numbered in ((False,False),(True,False),(False,True)):
                    outputs.extend(core.export_animation_psd(
                        self.resource,self.data,self.current_anim_name,dest,kind,safe,
                        frame_start=frame,frame_end=frame,numbered=numbered))
            msg=(f"已导出动画 {self.current_anim_name} 的时间轴第 {frame} 帧，共 {len(outputs)} 个 PSD。\n" if self.lang=="zh"
                 else f"Exported timeline frame {frame} of {self.current_anim_name}: {len(outputs)} PSD file(s).\n")
            self.status.set(msg.strip())
            messagebox.showinfo(self.T("title"),msg+str(dest))
        except Exception as e:
            traceback.print_exc(); messagebox.showerror(self.T("title"),str(e))

    def export_resource_psd(self):
        try:
            if not self.data or not self.resource: raise RuntimeError(self.T("need_parse"))
            out=Path(self.vars["output"].get().strip())
            if not out: raise RuntimeError(self.T("need_output"))
            dest=out/self.resource.stem/"resource_psd"; dest.mkdir(parents=True,exist_ok=True)
            if any(dest.iterdir()):
                if not messagebox.askyesno(self.T("title"),self.T("existing"),default=messagebox.YES): return
            count=0; summaries=[]
            for kind in self.selected_kinds():
                for safe,numbered in ((False,False),(True,False),(False,True)):
                    outs=core.export_resource_psd(self.resource,self.data,dest,kind,safe,numbered=numbered); count += len(outs)
                    for p,j,m,rp in outs: summaries.append(f"{p.name}: {len(m['layers'])} slices | {len(m['selected_animations'])} animations | {len(m['representative_frames'])} frames")
            self.status.set(f"v1.1: {count} resource PSD files")
            messagebox.showinfo(self.T("title"),self.status.get()+"\n\n"+"\n".join(summaries[:12])+"\n\n"+str(dest))
        except Exception as e:
            traceback.print_exc(); messagebox.showerror(self.T("title"),str(e))

    def open_find_cell_refs(self):
        """Find every parsed animation/frame that references a given Cell ID."""
        if self.resource is None:
            messagebox.showwarning(self.T("title"), self.T("scan_first")); return
        if not self.data:
            messagebox.showwarning(self.T("title"), self.T("need_parse")); return

        win = tk.Toplevel(self)
        win.title("检索切片动画引用" if self.lang == "zh" else "Find Cell Animation References")
        win.geometry("720x500")
        win.transient(self)
        win.columnconfigure(0, weight=1); win.rowconfigure(2, weight=1)
        desc = ("输入切片编号后，检索当前已解析资源中哪些动画引用了该 Cell，并列出对应帧号。只读取数据，不修改资源。"
                if self.lang == "zh" else
                "Enter a Cell number to find animations and timeline frames that reference it. This is read-only and does not modify the resource.")
        ttk.Label(win, text=desc, wraplength=680, justify="left").grid(row=0,column=0,sticky="ew",padx=12,pady=(12,8))
        bar=ttk.Frame(win); bar.grid(row=1,column=0,sticky="ew",padx=12,pady=(0,8)); bar.columnconfigure(1,weight=1)
        ttk.Label(bar,text="切片编号" if self.lang=="zh" else "Cell number").grid(row=0,column=0,padx=(0,8))
        cell_var=tk.StringVar()
        entry=ttk.Entry(bar,textvariable=cell_var,width=16); entry.grid(row=0,column=1,sticky="w")
        result=tk.Text(win,wrap="word",height=20); result.grid(row=2,column=0,sticky="nsew",padx=12,pady=(0,8))
        scroll=ttk.Scrollbar(win,orient="vertical",command=result.yview); scroll.grid(row=2,column=1,sticky="ns",pady=(0,8)); result.configure(yscrollcommand=scroll.set)
        status=tk.StringVar(value="请输入编号并点击检索。" if self.lang=="zh" else "Enter a Cell number and click Search.")
        ttk.Label(win,textvariable=status,anchor="w").grid(row=3,column=0,sticky="ew",padx=12,pady=(0,8))

        def search():
            raw=cell_var.get().strip()
            if not re.fullmatch(r"\d+",raw):
                messagebox.showwarning(self.T("title"), "请输入一个有效的非负整数切片编号。" if self.lang=="zh" else "Enter a valid non-negative integer Cell number.",parent=win); return
            cid=int(raw)
            try:
                usages, all_cells = core._build_cell_usage(self.resource,self.data)
                hits=[]
                for anim in usages:
                    frames=sorted(int(f) for f,cells in anim["frames"].items() if cid in cells)
                    if frames:
                        hits.append((anim["name"],frames,int(anim.get("frame_count",0))))
                result.delete("1.0","end")
                if not hits:
                    result.insert("end", (f"Cell {cid}：没有在当前解析到的动画中找到引用。" if self.lang=="zh" else f"Cell {cid}: no references found in the parsed animations."))
                    status.set("检索完成：0 个动画引用。" if self.lang=="zh" else "Search complete: 0 animation references.")
                    return
                lines=[]
                for name,frames,total in hits:
                    frame_text=", ".join(str(f) for f in frames)
                    lines.append(f"{name}  —  {len(frames)} 帧引用 / {total} 帧\n    帧号：{frame_text}")
                header = (f"Cell {cid} 被 {len(hits)} 个动画引用：\n\n" if self.lang=="zh" else f"Cell {cid} is referenced by {len(hits)} animations:\n\n")
                result.insert("end", header + "\n\n".join(lines))
                status.set((f"检索完成：{len(hits)} 个动画，{sum(len(x[1]) for x in hits)} 个动画帧引用。" if self.lang=="zh" else f"Search complete: {len(hits)} animations, {sum(len(x[1]) for x in hits)} animation-frame references."))
            except Exception as e:
                traceback.print_exc(); messagebox.showerror(self.T("title"),str(e),parent=win)
        ttk.Button(bar,text="检索" if self.lang=="zh" else "Search",command=search).grid(row=0,column=2,padx=(8,0))
        ttk.Button(win,text="关闭" if self.lang=="zh" else "Close",command=win.destroy).grid(row=4,column=0,sticky="e",padx=12,pady=(0,12))
        entry.bind("<Return>",lambda _e:search()); entry.focus_set()

    def open_frame_editor(self):
        if not self.resource or not self.data or not self.animation:
            messagebox.showinfo(self.T("title"), "请先解析资源并选择动画帧。" if self.lang=="zh" else "Parse a resource and select an animation frame first.")
            return
        FrameEditorWindow(self, self.resource, self.data, self.current_anim_name, int(self.frame))

    def save_recorded_animation_frames(self):
        FrameEditorWindow.save_recorded(self)

    def open_unlink_refs(self):
        """Open a non-destructive UEXP editor keyed by exported Cell numbers and animation."""
        if self.resource is None:
            messagebox.showwarning(self.T("title"), self.T("scan_first")); return
        # Reuse the exact animation list generated by Parse / Refresh Preview.
        # A separate UEXP parse can apply different filters for some resource types.
        if not self.data:
            messagebox.showwarning(
                self.T("title"),
                "请先点击“解析 / 刷新预览”，再解除切片动画引用。" if self.lang=="zh"
                else "Click Parse / Refresh Preview before editing animation references."
            ); return
        anim_names = list(dict.fromkeys(str(name) for name in self.animation_names if name))
        if not anim_names:
            messagebox.showwarning(
                self.T("title"),
                "当前资源没有可供选择的动画。" if self.lang=="zh"
                else "The current resource has no selectable animations."
            ); return
        win=tk.Toplevel(self); win.title(self.T("unlink_refs")); win.geometry("780x470"); win.transient(self)
        win.columnconfigure(1,weight=1)
        all_label = "全部动画（解除所有关联）" if self.lang=="zh" else "All animations (unlink all associations)"
        if self.lang=="zh":
            desc="输入导出 PNG/PSD 中的切片编号，选择目标动画，并可限定帧数区间（起止帧均包含）。仅解除所选动画中、Cell 关键帧落在区间内且匹配这些编号的引用；留空起止帧表示整个动画。选择“全部动画”时，会对每个动画应用相同区间。支持逗号、空格或换行分隔，不删除切片定义，原始资源不会被覆盖。"
            lab_ids="切片编号"; lab_anim="目标动画"; lab_range="帧数区间（包含起止帧）"; lab_start="起始帧"; lab_end="结束帧"; lab_out="输出目录"; browse="选择..."; run="分析并生成修改副本"; cancel="取消"
            warn="请先备份并在游戏中验证。最多填写 5 段区间，起止帧均包含；空白区间忽略。按已有 Cell 关键帧帧号筛选，不自动插入关键帧。匹配引用改为 None；若区间内没有可解除的 Cell 键，会自动把已有 Alpha 轨道同长度改写成 Hide（仅支持隐藏到动画末尾）。"
        else:
            desc="Enter exported PNG/PSD Cell numbers, choose an animation, and optionally limit edits to an inclusive frame range. Only matching Cell-reference keys whose keyframe index falls inside the range are unlinked; leave both range fields blank to target the whole animation. All animations applies the same range to each animation. Separate IDs with commas, spaces, or newlines. Cell definitions are retained and originals are never overwritten."
            lab_ids="Cell numbers"; lab_anim="Target animation"; lab_range="Frame range (inclusive)"; lab_start="Start frame"; lab_end="End frame"; lab_out="Output folder"; browse="Browse..."; run="Analyze and create patched copy"; cancel="Cancel"
            warn="Back up and test in game. Enter up to five inclusive frame ranges; blank rows are ignored. Filtering uses existing Cell-track keyframe indices and does not insert new keys. Matching references are rewritten to None. If no Cell key exists in the range, an existing Alpha track is rewritten to Hide in place (hide-to-animation-end only)."
        ttk.Label(win,text=desc,wraplength=720,justify="left").grid(row=0,column=0,columnspan=3,sticky="w",padx=12,pady=(12,8))
        ttk.Label(win,text=lab_ids).grid(row=1,column=0,sticky="nw",padx=12,pady=4)
        ids=tk.Text(win,height=4,width=55,wrap="word"); ids.grid(row=1,column=1,columnspan=2,sticky="ew",padx=(0,12),pady=4)
        ttk.Label(win,text=lab_anim).grid(row=2,column=0,sticky="w",padx=12,pady=4)
        animvar=tk.StringVar(value=all_label)
        anim_box=ttk.Combobox(win,state="readonly",textvariable=animvar,values=[all_label]+anim_names)
        anim_box.grid(row=2,column=1,columnspan=2,sticky="ew",padx=(0,12),pady=4)
        ttk.Label(win,text=lab_range).grid(row=3,column=0,sticky="nw",padx=12,pady=4)
        rangebox=ttk.Frame(win); rangebox.grid(row=3,column=1,columnspan=2,sticky="w",padx=(0,12),pady=4)
        range_vars=[]
        for ri in range(5):
            rowbox=ttk.Frame(rangebox); rowbox.pack(anchor="w", pady=1)
            ttk.Label(rowbox,text=(f"区间{ri+1}" if self.lang=="zh" else f"Range {ri+1}"),width=10).pack(side="left")
            ttk.Label(rowbox,text=lab_start).pack(side="left")
            sv=tk.StringVar(); ttk.Entry(rowbox,textvariable=sv,width=9).pack(side="left",padx=(5,12))
            ttk.Label(rowbox,text=lab_end).pack(side="left")
            ev=tk.StringVar(); ttk.Entry(rowbox,textvariable=ev,width=9).pack(side="left",padx=(5,0))
            range_vars.append((sv,ev))
        ttk.Label(win,text=lab_out).grid(row=4,column=0,sticky="w",padx=12,pady=4)
        _def_out = self.vars["output"].get().strip()
        if not _def_out:
            try:
                import kit.settings as _K
                _def_out = str(_K.output_psd())
            except Exception:
                _def_out = str(self.resource.uexp.parent)
        outvar=tk.StringVar(value=_def_out)
        ttk.Entry(win,textvariable=outvar).grid(row=4,column=1,sticky="ew",padx=(0,6),pady=4)
        def browse_out():
            chosen=filedialog.askdirectory(initialdir=outvar.get() or str(self.resource.uexp.parent),parent=win)
            if chosen: outvar.set(chosen)
        ttk.Button(win,text=browse,command=browse_out).grid(row=4,column=2,sticky="e",padx=(0,12),pady=4)
        ttk.Label(win,text=warn,wraplength=740,justify="left").grid(row=5,column=0,columnspan=3,sticky="w",padx=12,pady=8)
        btns=ttk.Frame(win); btns.grid(row=6,column=0,columnspan=3,sticky="e",padx=12,pady=(4,12))
        def execute():
            raw=ids.get("1.0","end").strip()
            nums=sorted(set(int(x) for x in re.findall(r"\d+",raw)))
            if not nums:
                messagebox.showwarning(self.T("title"), "请输入至少一个有效编号。" if self.lang=="zh" else "Enter at least one Cell number.",parent=win); return
            outroot=Path(outvar.get().strip())
            if not outroot.exists() or not outroot.is_dir():
                messagebox.showwarning(self.T("title"), "请选择已存在的输出目录。" if self.lang=="zh" else "Choose an existing output folder.",parent=win); return
            selected = None if animvar.get()==all_label else animvar.get()
            try:
                frame_ranges=[]
                for ri,(sv,ev) in enumerate(range_vars,1):
                    start_text=sv.get().strip(); end_text=ev.get().strip()
                    if not start_text and not end_text: continue
                    if bool(start_text) != bool(end_text):
                        raise ValueError((f"区间{ri}的起始帧和结束帧必须同时填写。" if self.lang=="zh" else f"Range {ri}: enter both start and end frames."))
                    start_frame=int(start_text); end_frame=int(end_text)
                    if start_frame<0 or end_frame<start_frame:
                        raise ValueError((f"区间{ri}无效：必须满足 0 ≤ 起始帧 ≤ 结束帧。" if self.lang=="zh" else f"Invalid range {ri}: require 0 <= start <= end."))
                    frame_ranges.append((start_frame,end_frame))
                # Merge overlapping/adjacent intervals to avoid duplicate processing.
                merged=[]
                for a,b in sorted(frame_ranges):
                    if merged and a<=merged[-1][1]+1: merged[-1]=(merged[-1][0],max(merged[-1][1],b))
                    else: merged.append((a,b))
                result=self._write_unlinked_resource(nums,outroot,selected_animation=selected,frame_ranges=merged)
                scope = all_label if selected is None else selected
                msg=(f"完成。\n目标动画：{scope}\n帧数区间：{', '.join(f'{a}~{b}' for a,b in result['frame_ranges']) if result['frame_ranges'] else '整个动画'}\n输入编号：{', '.join(map(str,nums))}\n实际解除引用的 Cell：{', '.join(map(str,result['matched_cells'])) or '无'}\n解除引用记录：{result['changed_refs']}\n涉及动画：{result['animations']}\n输出：{result['outdir']}" if self.lang=="zh" else f"Done.\nTarget animation: {scope}\nFrame ranges: {', '.join(f'{a}-{b}' for a,b in result['frame_ranges']) if result['frame_ranges'] else 'whole animation'}\nRequested Cell numbers: {', '.join(map(str,nums))}\nMatched Cells: {', '.join(map(str,result['matched_cells'])) or 'none'}\nReferences unlinked: {result['changed_refs']}\nAnimations affected: {result['animations']}\nOutput: {result['outdir']}")
                if result.get("mode")=="hide":
                    msg += ("\n\n没有可解除的 Cell 关键帧，已改为同长度改写 Alpha→Hide 轨道（不增删键）：\n  "
                            + "\n  ".join(result.get("notes") or []))
                messagebox.showinfo(self.T("title"),msg,parent=win); self.status.set(msg.replace("\n"," | ")); win.destroy()
            except Exception as e:
                traceback.print_exc(); messagebox.showerror(self.T("title"),str(e),parent=win)
        ttk.Button(btns,text=cancel,command=win.destroy).pack(side="right",padx=(6,0))
        ttk.Button(btns,text=run,command=execute).pack(side="right")

    def _insert_hide_keys(self, cell_numbers, output_root, selected_animation, frame_ranges):
        """同长度隐藏：把部件已有的 Alpha 轨道原地改成 Hide 轨道。

        已验证的规则（2026-10-23 游戏内通过）：
          - 只支持隐藏到动画末尾（end == end_frame）
          - Alpha 轨道至少 2 个键，且都使用 7 字节帧头 + byte 值编码
          - 第一键 -> 0 帧、值 0（显示）；第二键 -> start 帧、值 1（隐藏）
          - 原 Hide 轨道改名为 Rotz（值必须全 0），避免同部件两个 Hide
        不增删键、不改 uexp 长度、不改 uasset，因此不会触发序列化崩溃。
        """
        import struct as _st
        from v3inspect import transform_eval as te
        r = self.resource
        names, anims = te.parse_animations(r.uasset, r.uexp)
        te.attach_cells(r.uexp, names, anims)
        wanted = set(int(x) for x in cell_numbers)
        start_f, end_f = frame_ranges[0]
        b = bytearray(r.uexp.read_bytes())
        targets = []
        for a in anims:
            if selected_animation is not None and str(a.get("name", "")) != selected_animation:
                continue
            end_frame = int(a.get("end_frame") or a.get("frame_count") or 0)
            if end_f != end_frame:
                raise ValueError("目前只支持隐藏到动画末尾（结束帧 = 动画 end_frame）")
            for p in a.get("parts", []):
                cell_attr = next((x for x in p.attrs if x["name"] == "Cell"), None)
                if not cell_attr:
                    continue
                active = None
                for k in cell_attr["keys"]:
                    if k["frame"] <= start_f:
                        active = k
                if not active:
                    continue
                c = active.get("cell")
                if c is None or not getattr(c, "geometry_available", False):
                    continue
                if int(c.cell_id) not in wanted:
                    continue
                alpha = next((x for x in p.attrs if x["name"] == "Alpha"), None)
                if not alpha or len(alpha["keys"]) < 2:
                    raise ValueError(f"{a['name']}/{p.name}: 没有至少 2 个键的 Alpha 轨道，无法同长度改写成 Hide")
                k0, k1 = alpha["keys"][0], alpha["keys"][1]
                for k in (k0, k1):
                    if b[k["marker"] - 7:k["marker"] - 4] != bytes.fromhex("80 09 02"):
                        raise ValueError(f"{a['name']}/{p.name}: Alpha 键不是 7 字节帧头，暂不支持")
                    if b[k["marker"] + 3:k["marker"] + 7] != bytes.fromhex("80 09 06 03"):
                        raise ValueError(f"{a['name']}/{p.name}: Alpha 键不是 byte 值编码，暂不支持")
                hide = next((x for x in p.attrs if x["name"] == "Hide"), None)
                if hide:
                    if any(int(k["value"] or 0) != 0 for k in hide["keys"]):
                        raise ValueError(f"{a['name']}/{p.name}: 原 Hide 轨道含非 0 键，不能安全改名为 Rotz")
                    b[hide["start"] + 2] = 0x06          # Hide -> Rotz
                # 第一键 -> 0 帧 false；第二键 -> start 帧 true
                _st.pack_into("<I", b, k0["marker"] - 4, 0)
                b[k0["marker"] + 7] = 0
                _st.pack_into("<I", b, k1["marker"] - 4, start_f)
                b[k1["marker"] + 7] = 1
                b[alpha["start"] + 2] = 0x10             # Alpha -> Hide
                targets.append(f"{a['name']}/{p.name}: Hide [(0,0),({start_f},1)]")
        if not targets:
            raise ValueError("没有找到持有这些 Cell 的部件")
        outdir = Path(output_root) / f"{r.stem}_hide_range"
        if outdir.exists() and any(outdir.iterdir()):
            raise FileExistsError(f"输出目标已存在且非空：{outdir}")
        outdir.mkdir(parents=True, exist_ok=True)
        (outdir / r.uexp.name).write_bytes(bytes(b))
        shutil.copy2(r.uasset, outdir / r.uasset.name)
        # 验证长度与解析
        if (outdir / r.uexp.name).stat().st_size != r.uexp.stat().st_size:
            raise ValueError("内部错误：输出 uexp 长度变化")
        vn, va = te.parse_animations(outdir / r.uasset.name, outdir / r.uexp.name)
        te.attach_cells(outdir / r.uexp.name, vn, va)
        return {"frame_ranges": list(frame_ranges), "matched_cells": sorted(wanted),
                "changed_refs": 0, "animations": 1, "outdir": str(outdir),
                "mode": "hide", "notes": targets}

    def _write_unlinked_resource(self, cell_numbers, output_root, selected_animation=None, frame_range=None, frame_ranges=None):
        """Create a validated copy with selected Cells unreferenced in selected animation/keyframe range."""
        import hashlib
        from v3inspect import transform_eval as te
        r=self.resource
        names,anims=te.parse_animations(r.uasset,r.uexp)
        cells,records=te.attach_cells(r.uexp,names,anims)
        refs=core.ssa.parse_cell_refs(r.uexp)
        wanted=set(int(x) for x in cell_numbers)
        if frame_ranges is None:
            frame_ranges=[] if frame_range is None else [frame_range]
        frame_ranges=list(frame_ranges or [])
        valid={int(c.cell_id) for c in cells if c.geometry_available}
        # Number 0 is the synthetic atlas top-left crop emitted by the Analyzer; it has no UEXP Cell definition/reference.
        valid.add(0)
        unknown=sorted(wanted-valid)
        if unknown:
            raise ValueError(("这些编号不是当前资源中可导出的有效切片编号：" if self.lang=="zh" else "These are not valid exported Cell numbers for this resource: ")+", ".join(map(str,unknown)))
        to_change={}; by_anim={}
        for a in anims:
            if selected_animation is not None and str(a.get("name", "")) != selected_animation:
                continue
            for pi,p in enumerate(a.get("parts",[])):
                for attr in p.attrs:
                    if attr.get("name")!="Cell": continue
                    for k in attr.get("keys",[]):
                        # The range is inclusive and refers to existing Cell-track keyframe indices.
                        # We do not synthesize keys, which would require changing serialized UEXP layout.
                        key_frame=int(k.get("frame",-1))
                        if frame_ranges and not any(a <= key_frame <= b for a,b in frame_ranges):
                            continue
                        c=k.get("cell")
                        if c is None or not getattr(c,"geometry_available",False) or int(c.cell_id) not in wanted: continue
                        ro=int(k["reference_order"])
                        if not (0<=ro<len(refs)): raise ValueError(f"Invalid reference index {ro} while processing {a['name']}")
                        to_change[ro]=refs[ro]
                        by_anim.setdefault(a["name"],set()).add(int(c.cell_id))
        if not to_change:
            if wanted=={0}:
                raise ValueError("编号 0 是 Atlas 左上角补充导出帧，本身没有 UEXP 动画引用，无需解除。" if self.lang=="zh" else "Cell 0 is the synthetic top-left Atlas crop and has no UEXP animation reference to unlink.")
            if frame_ranges:
                return self._insert_hide_keys(wanted, output_root, selected_animation, frame_ranges)
            raise ValueError("指定编号没有在可解析的动画 Cell 轨道中找到引用；未生成修改文件。" if self.lang=="zh" else "No animation Cell-track references matched these numbers; no output was created.")
        original=r.uexp.read_bytes(); patched=bytearray(original); edits=[]
        for order,ref in sorted(to_change.items()):
            off=int(ref.offset); n=int(ref.length)
            if original[off:off+4] != bytes.fromhex("80 09 0E 01"):
                raise ValueError(f"Unexpected Cell reference header at 0x{off:X}; refusing to modify.")
            if struct.unpack_from("<I",original,off+4)[0] != n:
                raise ValueError(f"Reference length mismatch at 0x{off:X}; refusing to modify.")
            replacement=b"None"+b"\0"*(n-4)
            before=original[off+8:off+8+n]
            if len(before)!=n: raise ValueError(f"Truncated reference at 0x{off:X}")
            patched[off+8:off+8+n]=replacement
            edits.append({"reference_order":order,"offset_hex":hex(off),"old_name":ref.name,"new_name":"None","serialized_length":n})
        if len(patched)!=len(original): raise AssertionError("Patch changed UEXP length")
        # Validate parser compatibility and that every intended ref now resolves as None.
        temp=output_root / f".{r.stem}_validate_tmp.uexp"
        temp.write_bytes(patched)
        try:
            vrefs=core.ssa.parse_cell_refs(temp)
            if len(vrefs)!=len(refs): raise ValueError("Post-patch reference count changed")
            changed_orders={e["reference_order"] for e in edits}
            for i,(before_ref,after_ref) in enumerate(zip(refs,vrefs)):
                if i in changed_orders:
                    if after_ref.name!="None": raise ValueError("Post-patch None reference validation failed")
                elif before_ref.name!=after_ref.name:
                    raise ValueError(f"Unexpected unrelated reference change at order {i}")
            vnames,vanims=te.parse_animations(r.uasset,temp)
            vcells,vrecords=te.attach_cells(temp,vnames,vanims)
            for a in vanims:
                for p in a.get("parts",[]):
                    for attr in p.attrs:
                        if attr.get("name")=="Cell":
                            for k in attr.get("keys",[]):
                                if k.get("reference_order") in to_change and k.get("reference")!="None":
                                    raise ValueError("Post-patch animation association validation failed")
        finally:
            try: temp.unlink()
            except OSError: pass
        outdir=Path(output_root)/f"{r.stem}_animation_refs_removed"
        if outdir.exists() and any(outdir.iterdir()):
            raise FileExistsError(("输出目标已存在且非空，为防止覆盖请更换输出目录：" if self.lang=="zh" else "Output package already exists and is non-empty; choose another output folder: ")+str(outdir))
        outdir.mkdir(parents=True,exist_ok=True); (outdir/"original_backup").mkdir()
        shutil.copy2(r.uasset,outdir/r.uasset.name)
        (outdir/r.uexp.name).write_bytes(patched)
        shutil.copy2(r.uexp,outdir/"original_backup"/r.uexp.name)
        for tex in r.textures().values():
            if tex and tex.exists(): shutil.copy2(tex,outdir/tex.name)
        report={"operation":"unlink_animation_cell_references","resource":r.stem,"requested_cell_ids":sorted(wanted),"selected_animation":selected_animation or "ALL","frame_ranges_inclusive":[list(x) for x in frame_ranges] if frame_ranges else None,"matched_cell_ids":sorted({int(c.cell_id) for c in cells if c.geometry_available and int(c.cell_id) in wanted}),"changed_reference_count":len(edits),"affected_animations":{k:sorted(v) for k,v in sorted(by_anim.items())},"original_uexp_size":len(original),"patched_uexp_size":len(patched),"original_sha256":hashlib.sha256(original).hexdigest(),"patched_sha256":hashlib.sha256(patched).hexdigest(),"edits":edits,"validation":{"same_file_size":len(original)==len(patched),"same_reference_count":len(refs)==len(vrefs),"only_selected_reference_names_changed":all((vrefs[i].name=="None") if i in {e["reference_order"] for e in edits} else (refs[i].name==vrefs[i].name) for i in range(len(refs))),"patched_refs_parse_as_none":True,"animation_parser_passed":True,"runtime_game_tested":False}}
        (outdir/"animation_reference_unlink_report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
        (outdir/"README_TEST.txt").write_text(("本目录为非破坏性实验副本。目标动画范围："+(selected_animation or "全部动画")+"。将本目录中的 .uasset、修改后的 .uexp 与同名纹理放入测试资源目录后进行游戏验证。original_backup 中保存原始 .uexp。目标编号的动画 Cell 引用被改写为 None，切片定义未删除。已通过文件长度、引用数量和解析器结构检查；未进行游戏运行时验证。\n" if self.lang=="zh" else "Non-destructive test copy. Target animation: "+(selected_animation or "ALL animations")+". Test the .uasset, patched .uexp, and textures together in game. original_backup contains the original .uexp. Animation references for requested Cell numbers were rewritten to None; Cell definitions remain. Structural checks passed; runtime game behavior is not verified.\n"),encoding="utf-8")
        return {"outdir":str(outdir),"matched_cells":report["matched_cell_ids"],"changed_refs":len(edits),"animations":len(by_anim),"selected_animation":selected_animation or "ALL","frame_ranges":frame_ranges}

    def export_crops(self):
        try:
            if not self.resource or not self.data: raise RuntimeError(self.T("need_parse"))
            out=Path(self.vars["output"].get().strip())/self.resource.stem
            names=self.data["names"]; cells,_=core.ssa.parse_cell_defs(self.resource.uexp,names)
            if self.resource.tex:
                im=Image.open(self.resource.tex).convert("RGBA"); origin=core.ssa.make_atlas_origin_cell(im,cells)
                if origin and not any(c.geometry_available and c.cell_id==0 for c in cells): cells.insert(0,origin)
            core.ssa.export_texture_crops(self.resource,out,cells,True,only_missing=False)
            self.status.set(str(out)); messagebox.showinfo(self.T("title"),str(out))
        except Exception as e: messagebox.showerror(self.T("title"),str(e))

    def export_gif(self):
        try:
            if not self.data or not self.animation or not self.resource or not self.resource.tex:
                raise RuntimeError(self.T("need_parse"))
            out=Path(self.vars["output"].get().strip())/self.resource.stem/"gif"
            out.mkdir(parents=True,exist_ok=True)
            frames=[]
            total=int(self.animation.get("frame_count") or 0)
            for f in range(total):
                im,_=core.render_animation_frame(self.resource,self.data,self.current_anim_name,f,"tex")
                frames.append(im.convert("RGBA"))
            if not frames: raise RuntimeError("No frames to export")
            duration=max(20,int(1000/max(1,int(self.animation.get("fps") or 30))))
            path=out/f"{core.safe_name(self.current_anim_name)}.gif"
            frames[0].save(path,save_all=True,append_images=frames[1:],duration=duration,loop=0,disposal=2,optimize=False,transparency=0)
            self.status.set(str(path)); messagebox.showinfo(self.T("title"),str(path))
        except Exception as e:
            traceback.print_exc(); messagebox.showerror(self.T("title"),str(e))

    def pick_atlas(self):
        p=filedialog.askopenfilename(filetypes=[("PNG","*.png"),("All files","*.*")])
        if p: self.vars["atlas"].set(p); self.save_settings()
    def pick_psd(self):
        p=filedialog.askopenfilename(filetypes=[("PSD","*.psd"),("All files","*.*")])
        if p: self.vars["psd"].set(p); self.save_settings()
    def pick_recover_out(self):
        p=filedialog.askdirectory()
        if p: self.vars["outpng"].set(p); self.save_settings()
    def check_psd(self):
        try:
            psd=Path(self.vars["psd"].get().strip())
            if not psd.exists(): raise FileNotFoundError(self.T("need_psd"))
            out_text=self.vars["outpng"].get().strip()
            report_path, report=core.check_psd_layers(psd, Path(out_text) if out_text else psd.parent)
            sm=report["summary"]
            msg=(f"图层总数：{sm['leaf_layer_count']}\n命名不符合规则：{sm['nonconforming_layer_count']}\n重复图层名组：{sm['duplicate_exact_name_groups']}\n重复工具身份组：{sm['duplicate_tool_identity_groups']}\n\n报告仅记录有问题的图层/Cell。\n报告：{report_path}")
            self.status.set("PSD 图层检查完成" if self.lang=="zh" else "PSD layer check complete")
            (messagebox.showwarning if sm['issue_count'] else messagebox.showinfo)(self.T("title"),msg)
        except Exception as e:
            traceback.print_exc(); messagebox.showerror(self.T("title"),str(e))

    def compare_psd_layers(self):
        try:
            edited=Path(self.vars["psd"].get().strip())
            if not edited.exists(): raise FileNotFoundError(self.T("need_psd"))
            reference=filedialog.askopenfilename(title="选择原始导出的 PSD（作为对照）" if self.lang=="zh" else "Select originally exported PSD as reference",filetypes=[("PSD","*.psd"),("All files","*.*")])
            if not reference: return
            out_text=self.vars["outpng"].get().strip()
            report_path,report=core.check_psd_layers(edited,Path(out_text) if out_text else edited.parent,Path(reference))
            sm=report["summary"]
            msg=(f"新增图层：{sm['added_layer_count']}\n缺失图层：{sm['missing_layer_count']}\n命名问题图层：{sm['nonconforming_layer_count']}\n重复图层名组：{sm['duplicate_exact_name_groups']}\n重复工具身份组：{sm['duplicate_tool_identity_groups']}\n\n报告仅记录有问题的图层和对应 Cell。\n报告：{report_path}")
            self.status.set("PSD 图层对比完成" if self.lang=="zh" else "PSD layer comparison complete")
            (messagebox.showwarning if sm['issue_count'] else messagebox.showinfo)(self.T("title"),msg)
        except Exception as e:
            traceback.print_exc(); messagebox.showerror(self.T("title"),str(e))

    def recover_psd(self):
        try:
            if not self.data or not self.resource: raise RuntimeError(self.T("need_parse"))
            psd=Path(self.vars["psd"].get().strip()); atlas=Path(self.vars["atlas"].get().strip()); out=Path(self.vars["outpng"].get().strip())
            if not psd.exists(): raise FileNotFoundError(self.T("need_psd"))
            if not atlas.exists(): raise FileNotFoundError(self.T("need_atlas"))
            if not out: raise RuntimeError(self.T("need_output"))
            # Match texture kind from the selected PSD filename; otherwise use the UI selection.
            stem=psd.stem.lower(); kind="tex"
            for k in ("normal","mreo","tex"):
                if f"_{k}_" in stem or stem.endswith("_"+k): kind=k; break
            result=core.recover_psd(psd,self.resource,self.data,kind,out,atlas)
            conflicts=result[2]
            if conflicts:
                self.status.set(self.T("recover_conflict",n=len(conflicts))); messagebox.showwarning(self.T("title"),self.status.get()+"\n\n"+str(result[1]))
            else:
                report=json.loads(Path(result[1]).read_text(encoding="utf-8")); changed=report.get("summary",{}).get("changed_source_pixels",0)
                mode=report.get("mode","animation"); anim=report.get("animation")
                scope=("全部切片" if mode=="resource" else f"当前动画：{anim}（仅合并 PSD 中包含的切片，其他像素保持原样）")
                diagnostics=report.get("diagnostics",[])
                errors=[d for d in diagnostics if d.get("status")=="error"]
                self.status.set(self.T("recover_done",c=changed))
                message=self.status.get()+f"\n还原范围：{scope}\n\n输出：{result[0]}\n报告：{result[1]}"
                if errors:
                    cells=sorted({str(d.get("cell_id") or __import__('re').search(r'__Cell_(\d+)',str(d.get('layer',''))).group(1)) for d in errors if d.get("cell_id") is not None or __import__('re').search(r'__Cell_(\d+)',str(d.get('layer','')))})
                    message+=f"\n\n注意：有 {len(errors)} 个图层未能安全还原，涉及 Cell：{', '.join(cells) if cells else '无法识别'}。请查看 recovery_report.json 的 diagnostics。"
                    messagebox.showwarning(self.T("title"),message)
                else:
                    messagebox.showinfo(self.T("title"),message)
        except Exception as e:
            traceback.print_exc(); messagebox.showerror(self.T("title"),str(e))

    def clear_preview(self):
        self.anim_box["values"]=[]; self.anim_box.set(""); self.anim_list.delete(0,"end"); self.layer_list.delete(0,"end"); self.info.delete("1.0","end"); self.canvas.delete("all"); self.animation=None
    def load_settings(self):
        p=SETTINGS_DIR/SETTINGS_NAME
        try:
            d=json.loads(p.read_text(encoding="utf-8")); self.lang=d.get("language","zh")
            try:
                import kit.settings as _K
                self.lang = str(_K.load().get("ui_lang") or self.lang)
            except Exception:
                pass; self.speed.set(d.get("speed","0.5x")); self.texture_mode.set(d.get("texture_mode","all"));
            for k,v in d.get("paths",{}).items():
                if k in ("resource","atlas","psd","outpng") and k in self.vars: self.vars[k].set(v)
        except Exception: pass
        # ★ 输入/输出始终取自 Toolkit 首页，避免旧路径残留
        try:
            import kit.settings as _K
            if "input" in self.vars: self.vars["input"].set(str(_K.input_psd()))
            if "output" in self.vars: self.vars["output"].set(str(_K.output_psd()))
        except Exception: pass
    def save_settings(self):
        try:
            (SETTINGS_DIR/SETTINGS_NAME).write_text(json.dumps({"language":self.lang,"speed":self.speed.get(),"texture_mode":self.texture_mode.get(),"paths":{k:v.get() for k,v in self.vars.items() if k in ("resource","atlas","psd","outpng")}},ensure_ascii=False,indent=2),encoding="utf-8")
        except Exception: pass
    def close(self):
        if self.after_id:
            try:self.after_cancel(self.after_id)
            except Exception:pass
        self.save_settings(); self.destroy()


class FrameEditorWindow(tk.Toplevel):
    """Per-frame transform editor with staged multi-Part changes and conservative UEXP writes."""
    def __init__(self, app, resource, data, animation_name, frame):
        super().__init__(app)
        self.app=app; self.resource=resource; self.data=data; self.anim_name=animation_name; self.frame=int(frame)
        self.title(f"编辑动画帧 - {animation_name} / Frame {frame}"); self.geometry("1180x780"); self.minsize(940,640)
        self.selected=None; self._drag=None; self.preview_photo=None; self.preview_scale=1.0; self.canvas_origin=(0,0); self.rows=[]; self.info=None
        # Part index -> accumulated temporary canvas-space pixel delta. Nothing is written until Save.
        self._pending_deltas={}; self._outline_after=None; self._outline_visible=False; self._refreshing_layers=False; self._layer_signature=None
        root=ttk.Frame(self,padding=8); root.pack(fill="both",expand=True); root.columnconfigure(0,weight=4); root.columnconfigure(1,weight=2); root.rowconfigure(0,weight=1)
        left=ttk.Frame(root); left.grid(row=0,column=0,sticky="nsew",padx=(0,8)); left.rowconfigure(1,weight=1); left.columnconfigure(0,weight=1)
        ttk.Label(left,text=f"动画：{animation_name}    帧：{frame}    | 左键选择并拖动切片",anchor="w").grid(row=0,column=0,sticky="ew")
        self.canvas=tk.Canvas(left,bg="#202020",highlightthickness=0,cursor="crosshair"); self.canvas.grid(row=1,column=0,sticky="nsew",pady=5)
        self.canvas.bind("<Configure>",lambda e:self.render()); self.canvas.bind("<ButtonPress-1>",self.press); self.canvas.bind("<B1-Motion>",self.motion); self.canvas.bind("<ButtonRelease-1>",self.release)
        # Keyboard nudge is canvas-focus-only; never bind_all, so Listbox navigation cannot change the selected Part.
        self.canvas.bind("<KeyPress-w>",lambda e:self.nudge(0,-1)); self.canvas.bind("<KeyPress-W>",lambda e:self.nudge(0,-1))
        self.canvas.bind("<KeyPress-s>",lambda e:self.nudge(0,1)); self.canvas.bind("<KeyPress-S>",lambda e:self.nudge(0,1))
        self.canvas.bind("<KeyPress-a>",lambda e:self.nudge(-1,0)); self.canvas.bind("<KeyPress-A>",lambda e:self.nudge(-1,0))
        self.canvas.bind("<KeyPress-d>",lambda e:self.nudge(1,0)); self.canvas.bind("<KeyPress-D>",lambda e:self.nudge(1,0))
        right=ttk.Frame(root); right.grid(row=0,column=1,sticky="nsew"); right.rowconfigure(1,weight=1); right.columnconfigure(0,weight=1)
        ttk.Label(right,text="当前帧切片图层 / Part 信息").grid(row=0,column=0,sticky="w")
        self.layers=tk.Listbox(right,exportselection=False); self.layers.grid(row=1,column=0,sticky="nsew",pady=5); self.layers.bind("<<ListboxSelect>>",self.list_select)
        self.details=tk.Text(right,height=12,width=38); self.details.grid(row=2,column=0,sticky="ew",pady=(0,5))
        bar=ttk.Frame(right); bar.grid(row=3,column=0,sticky="ew"); bar.columnconfigure(0,weight=1)
        ttk.Button(bar,text="跳转到可保存帧",command=self.jump_editable_frame).grid(row=0,column=0,sticky="ew",pady=(0,4))
        ttk.Button(bar,text="记录当前修改（不写入）",command=self.record_pending).grid(row=1,column=0,sticky="ew")
        self.save_btn=ttk.Button(bar,text="保存本窗口位置到 UEXP…",command=self.save); self.save_btn.grid(row=2,column=0,sticky="ew",pady=(4,0))
        ttk.Button(bar,text="撤销当前切片移动",command=self.undo_selected).grid(row=3,column=0,sticky="ew",pady=(4,0))
        ttk.Label(right,text="先用“记录当前修改”将本动画帧的调整加入程序缓存，关闭窗口后仍会保留。可继续编辑其他动画帧，最后点击主界面的“保存动画帧”一次性写入 UEXP。未记录的修改关闭后会丢弃。",wraplength=310,foreground="#555555").grid(row=4,column=0,sticky="ew",pady=(8,0))
        # WASD nudge intentionally disabled: keyboard focus/listbox refresh could change the
        # selected Part during editing. Use deterministic mouse drag only in this build.
        self.bind("<Escape>",lambda e:self.destroy())
        self.render(); self.focus_set()

    def render(self):
        try:
            self.image,self.info=core.render_animation_frame(self.resource,self.data,self.anim_name,self.frame,"tex")
            self.rows=self.info["layers"]; self.canvas.delete("all")
            # Rehydrate edits previously recorded for this exact animation/frame.
            rpath=str(self.resource.uexp.resolve())
            for rr in self.rows:
                key=(rpath,self.anim_name,int(self.frame),int(rr.part_index))
                if key in self.app._recorded_frame_edits and rr.part_index not in self._pending_deltas:
                    self._pending_deltas[rr.part_index]=tuple(self.app._recorded_frame_edits[key])
            cw=max(1,self.canvas.winfo_width()); ch=max(1,self.canvas.winfo_height()); iw,ih=self.image.size
            self.preview_scale=min(max(1,cw-24)/iw,max(1,ch-24)/ih,5.0)
            size=(max(1,round(iw*self.preview_scale)),max(1,round(ih*self.preview_scale)))
            shown=self.make_edit_preview(); resized=shown.resize(size,Image.Resampling.NEAREST); self.preview_photo=ImageTk.PhotoImage(resized)
            x=(cw-size[0])//2; y=(ch-size[1])//2; self.canvas_origin=(x,y)
            self.canvas.create_image(x,y,image=self.preview_photo,anchor="nw",tags=("frame",))
            # Rebuild the layer list only when the actual frame layer set changes.
            # Recreating Listbox items during drag can emit delayed selection events and
            # unexpectedly switch the active Part on Windows/Tk.
            signature=tuple((r.part_index,r.cell_id,r.part_name) for r in self.rows)
            if signature != self._layer_signature:
                self._refreshing_layers=True
                try:
                    self.layers.delete(0,"end")
                    for r in self.rows:
                        self.layers.insert("end",f"Part_{r.part_index:03d} | Cell_{r.cell_id} | {r.part_name}")
                    indices=[i for i,r in enumerate(self.rows) if r.part_index==self.selected] if self.selected is not None else []
                    if indices:
                        self.selected=indices[0]; self.layers.selection_set(self.selected); self.layers.see(self.selected)
                    self._layer_signature=signature
                finally:self._refreshing_layers=False
            if self._outline_visible:self.highlight()
            self.update_details()
        except Exception as e:
            self.canvas.delete("all"); self.canvas.create_text(20,20,anchor="nw",text=str(e),fill="orange")

    def make_edit_preview(self):
        out=Image.new("RGBA",self.image.size,(0,0,0,0))
        for r in self.rows:
            x,y,w,h=r.bbox; dx,dy=self._pending_deltas.get(r.part_index,(0.0,0.0))
            out.alpha_composite(r.image.convert("RGBA"),(int(round(x+dx)),int(round(y+dy))))
        return out

    def _show_outline(self):
        self._outline_visible=True
        if self._outline_after:
            try:self.after_cancel(self._outline_after)
            except Exception:pass
        self.highlight(); self._outline_after=self.after(3000,self._hide_outline)

    def _hide_outline(self):
        self._outline_visible=False; self._outline_after=None; self.canvas.delete("selection")

    def highlight(self):
        self.canvas.delete("selection")
        if not self._outline_visible or self.selected is None or self.selected>=len(self.rows):return
        r=self.rows[self.selected]; x,y,w,h=r.bbox; dx,dy=self._pending_deltas.get(r.part_index,(0.0,0.0)); ox,oy=self.canvas_origin; sc=self.preview_scale
        self.canvas.create_rectangle(ox+(x+dx)*sc,oy+(y+dy)*sc,ox+(x+w+dx)*sc,oy+(y+h+dy)*sc,outline="#00e5ff",width=2,tags=("selection",))

    def select_index(self,i):
        if not 0<=i<len(self.rows):return
        self.selected=i; self._show_outline(); self.update_details()
        self._refreshing_layers=True
        try:self.layers.selection_clear(0,"end"); self.layers.selection_set(i); self.layers.see(i)
        finally:self._refreshing_layers=False

    def list_select(self,_=None):
        if self._refreshing_layers:return
        ss=self.layers.curselection()
        if ss:
            idx=int(ss[0])
            if idx == self.selected:
                return
            self.selected=idx; self._show_outline(); self.update_details()

    def update_details(self):
        self.details.delete("1.0","end")
        if self.selected is None or self.selected>=len(self.rows):return
        r=self.rows[self.selected]; anim=core.animation_by_name(self.data,self.anim_name); part=anim["parts"][r.part_index]; attrs=te.attr_map(part)
        xkey=self.exact_key(attrs.get("Posx"),self.frame); ykey=self.exact_key(attrs.get("Posy"),self.frame); dx,dy=self._pending_deltas.get(r.part_index,(0.0,0.0))
        state={"animation":self.anim_name,"frame":self.frame,"part_index":r.part_index,"part_name":r.part_name,"cell_id":r.cell_id,"node_id":r.node_id,"parent_id":r.parent_id,"local_position":{"x":r.local.get("x"),"y":r.local.get("y")},"temporary_screen_delta":{"x":round(dx,3),"y":round(dy,3)},"editable_exact_frame_keys":{"Posx":bool(xkey),"Posy":bool(ykey)},"save_allowed":bool(xkey and ykey),"pending_parts":len(self._pending_deltas),"note":"当前帧有精确位置关键帧，可保存。" if xkey and ykey else "当前帧没有完整的 Posx/Posy 精确关键帧；可点击“跳转到可保存帧”。临时位移会保留。"}
        self.details.insert("end",json.dumps(state,ensure_ascii=False,indent=2))

    @staticmethod
    def exact_key(attr,frame):
        if not attr:return None
        for k in attr.get("keys",[]):
            if int(k.get("frame",-1))==int(frame):return k
        return None

    def canvas_point(self,event):
        ox,oy=self.canvas_origin; return ((event.x-ox)/self.preview_scale,(event.y-oy)/self.preview_scale)

    def press(self,event):
        self.canvas.focus_set()
        ox,oy=self.canvas_origin; iw,ih=self.image.size
        if event.x<ox or event.y<oy or event.x>=ox+iw*self.preview_scale or event.y>=oy+ih*self.preview_scale:
            self._drag=None; return
        px,py=self.canvas_point(event)
        for i in range(len(self.rows)-1,-1,-1):
            r=self.rows[i]; x,y,w,h=r.bbox; dx,dy=self._pending_deltas.get(r.part_index,(0.0,0.0)); lx=int(math.floor(px-x-dx)); ly=int(math.floor(py-y-dy))
            if 0<=lx<w and 0<=ly<h:
                try:alpha=r.image.getpixel((lx,ly))[3]
                except Exception:alpha=0
                if alpha>32:
                    self.select_index(i); base=self._pending_deltas.get(r.part_index,(0.0,0.0)); self._drag=(event.x,event.y,i,base[0],base[1]); return
        self._drag=None

    def motion(self,event):
        if not self._drag:return
        sx,sy,i,bx,by=self._drag; r=self.rows[i]
        dx=bx+(event.x-sx)/self.preview_scale; dy=by+(event.y-sy)/self.preview_scale
        self._pending_deltas[r.part_index]=(dx,dy); self.selected=i; self.render(); self._show_outline()

    def release(self,event=None):
        if not self._drag:return
        sx,sy,i,bx,by=self._drag; r=self.rows[i]
        if event is not None:self._pending_deltas[r.part_index]=(bx+(event.x-sx)/self.preview_scale,by+(event.y-sy)/self.preview_scale)
        self._drag=None; self.render(); self._show_outline(); self.update_details()

    def nudge(self,dx,dy):
        if self.selected is None or self.selected>=len(self.rows):return
        r=self.rows[self.selected]; ox,oy=self._pending_deltas.get(r.part_index,(0.0,0.0)); self._pending_deltas[r.part_index]=(ox+dx,oy+dy)
        self.render(); self._show_outline(); self.update_details()

    def undo_selected(self):
        if self.selected is None or self.selected>=len(self.rows):return
        self._pending_deltas.pop(self.rows[self.selected].part_index,None); self.render(); self._show_outline(); self.update_details()

    def _frame_count(self):
        anim=core.animation_by_name(self.data,self.anim_name)
        return max(1,int(anim.get("frame_count",anim.get("end_frame",self.frame+1))))

    def _frame_editable_for_parts(self,frame,part_indices):
        anim=core.animation_by_name(self.data,self.anim_name)
        for pi in part_indices:
            if pi>=len(anim["parts"]):return False
            attrs=te.attr_map(anim["parts"][pi])
            if not self.exact_key(attrs.get("Posx"),frame) or not self.exact_key(attrs.get("Posy"),frame):return False
        # A valid key is not enough: every staged Part must also be drawable in the target frame.
        try:
            _, info=core.render_animation_frame(self.resource,self.data,self.anim_name,frame,"tex")
            visible={r.part_index for r in info.get("layers",[])}
            if any(pi not in visible for pi in part_indices):return False
        except Exception:return False
        return True

    def _other_animation_candidates(self, target_parts):
        """Find likely exact-key frames in other animations for diagnostics only; never auto-switch."""
        found=[]
        for anim in self.data.get("animations",[]):
            name=str(anim.get("name", ""))
            if not name or name==self.anim_name or anim.get("header_type")=="Setup":
                continue
            mapped=[]
            possible=True
            for pi in target_parts:
                source = next((r for r in self.rows if r.part_index==pi), None)
                if source is None:
                    possible=False; break
                matches=[]
                for oi, part in enumerate(anim.get("parts", [])):
                    attrs=te.attr_map(part)
                    if not self.exact_key(attrs.get("Posx"),0) and not attrs.get("Posx"):
                        continue
                    # Match by stable node/part identity first, then by part name + Cell.
                    same_node=(source.node_id is not None and getattr(part,"node_id",None)==source.node_id)
                    pname=str(getattr(part,"name", ""))
                    same_name=bool(source.part_name and pname==source.part_name)
                    same_cell=False
                    try:
                        cattr=te.attr_map(part).get("Cell")
                        same_cell=bool(cattr and int(cattr.get("value",-999))==int(source.cell_id))
                    except Exception: pass
                    if same_node or (same_name and same_cell):
                        matches.append(oi)
                if not matches:
                    possible=False; break
                mapped.append(matches[0])
            if not possible: continue
            maxframe=max(1,int(anim.get("frame_count",anim.get("end_frame",1))))
            candidates=[]
            for f in range(maxframe):
                ok=True
                for oi in mapped:
                    attrs=te.attr_map(anim["parts"][oi])
                    if not self.exact_key(attrs.get("Posx"),f) or not self.exact_key(attrs.get("Posy"),f):
                        ok=False; break
                if ok:candidates.append(f)
            if candidates:
                # Also check that the candidate actually renders the mapped parts.
                for f in candidates:
                    try:
                        _,inf=core.render_animation_frame(self.resource,self.data,name,f,"tex")
                        visible={r.part_index for r in inf.get("layers",[])}
                        if all(i in visible for i in mapped):
                            found.append((name,f)); break
                    except Exception: pass
        return found

    def jump_editable_frame(self):
        targets=list(self._pending_deltas) or ([self.rows[self.selected].part_index] if self.selected is not None and self.selected<len(self.rows) else [])
        if not targets:messagebox.showwarning(self.title(),"请先选择一个切片，或先调整切片位置。",parent=self);return
        count=self._frame_count(); candidates=[f for f in range(count) if self._frame_editable_for_parts(f,targets)]
        if not candidates:
            other=self._other_animation_candidates(targets)
            if other:
                details="\n".join(f"• {name} / Frame {frame}" for name,frame in other[:12])
                suffix=("\n\n在当前动画中没有符合条件的帧；检测到可能可编辑的位置在其他动画：\n"+details+
                        ("\n（仅显示前 12 项）" if len(other)>12 else "")+
                        "\n\n本窗口不会自动切换动画，以免将临时位移误写入不同动画。临时修改仍保留。")
            else:
                suffix="\n\n在已解析的其他动画中也未找到能可靠匹配这些切片的完整 Posx/Posy 精确关键帧。临时修改仍保留。"
            messagebox.showerror(self.title(),"在此动画中没有找到同时具备完整 Posx/Posy 精确关键帧的帧。"+suffix,parent=self);return
        new=min(candidates,key=lambda f:(abs(f-self.frame),f)); old=self.frame; self.frame=new
        self.title(f"编辑动画帧 - {self.anim_name} / Frame {new}"); self.render()
        messagebox.showinfo(self.title(),f"已从 Frame {old} 跳转到最近的可保存帧 Frame {new}。\n临时切片位移已保留；保存会写入当前帧。",parent=self)

    def _patch_key(self,bdata,k,val):
        pos=int(k["marker"])+3; typ=k.get("value_type")
        if typ=="int":struct.pack_into("<i",bdata,pos+4,int(round(val)))
        elif typ=="uint":
            iv=int(round(val))
            if not 0<=iv<=0xFFFFFFFF:raise ValueError("uint position out of range")
            struct.pack_into("<I",bdata,pos+4,iv)
        elif typ=="float":struct.pack_into("<f",bdata,pos+4,float(val))
        elif typ=="byte":
            if not -128<=int(round(val))<=127:raise ValueError("byte position out of range")
            struct.pack_into("<b",bdata,pos+4,int(round(val)))
        else:raise ValueError(f"不支持的 Posx/Posy 数值编码：{typ}")

    def record_pending(self):
        if not self._pending_deltas:
            messagebox.showinfo(self.title(), "当前没有需要记录的位置修改。", parent=self); return
        rpath=str(self.resource.uexp.resolve())
        anim=core.animation_by_name(self.data,self.anim_name)
        staged=[]
        for pi, delta in self._pending_deltas.items():
            if pi < 0 or pi >= len(anim.get("parts", [])):
                messagebox.showerror(self.title(),f"Part {pi} 不存在，未记录。",parent=self); return
            attrs=te.attr_map(anim["parts"][pi])
            xk=self.exact_key(attrs.get("Posx"),self.frame); yk=self.exact_key(attrs.get("Posy"),self.frame)
            if not xk or not yk:
                messagebox.showerror(self.title(),f"{self.anim_name} / Frame {self.frame} / Part {pi} 缺少完整 Posx/Posy 精确关键帧。\n请先跳转到可保存帧。\n本次没有记录任何修改。",parent=self); return
            staged.append(((rpath,self.anim_name,int(self.frame),int(pi)),(float(delta[0]),float(delta[1]))))
        self.app._recorded_frame_edits.update(staged)
        messagebox.showinfo(self.title(),f"已将 {len(staged)} 个切片的修改记录到程序缓存。\n当前记录总数：{len(self.app._recorded_frame_edits)} 项。\n这些修改尚未写入 UEXP；关闭本窗口后仍会保留在本次程序运行期间。",parent=self)

    @staticmethod
    def save_recorded(app):
        records=getattr(app,"_recorded_frame_edits",{})
        if not records:
            messagebox.showinfo(app.T("title"),"缓存中没有已记录的动画帧修改。请先在编辑窗口点击“记录当前修改”。"); return
        if app.resource is None or app.data is None:
            messagebox.showerror(app.T("title"),"请先解析原始资源，再保存记录的动画帧修改。"); return
        rpath=str(app.resource.uexp.resolve())
        foreign=[k for k in records if k[0]!=rpath]
        if foreign:
            messagebox.showerror(app.T("title"),"缓存中存在其他资源的修改。请先切换回记录这些修改时使用的原始资源，再保存，避免写入错误的 UEXP。"); return
        outdir=filedialog.askdirectory(parent=app,title="选择批量保存动画帧修改的输出目录")
        if not outdir:return
        bdata=bytearray(app.resource.uexp.read_bytes()); report=[]
        try:
            # Group by animation/frame so transforms and render-layer identity are evaluated against each target frame.
            grouped={}
            for (rp,an,fr,pi),delta in records.items(): grouped.setdefault((an,int(fr)),{})[int(pi)]=delta
            for (aname,frame),parts_deltas in grouped.items():
                anim=core.animation_by_name(app.data,aname)
                _,info=core.render_animation_frame(app.resource,app.data,aname,frame,"tex")
                rows={r.part_index:r for r in info.get("layers",[])}
                states=te.make_frame_state(anim,frame,app.data["static_map"]); worlds=te.world_matrices(states)
                for pi,(dx,dy) in parts_deltas.items():
                    if pi not in rows: raise ValueError(f"{aname} / Frame {frame}: Part {pi} 在该帧不可见，无法安全写入。")
                    part=anim["parts"][pi]; attrs=te.attr_map(part)
                    xk=FrameEditorWindow.exact_key(attrs.get("Posx"),frame); yk=FrameEditorWindow.exact_key(attrs.get("Posy"),frame)
                    if not xk or not yk: raise ValueError(f"{aname} / Frame {frame} / Part {pi}: 缺少完整 Posx/Posy 精确关键帧。")
                    rr=rows[pi]; pm=worlds.get(rr.parent_id,(1,0,0,1,0,0)) if rr.parent_id is not None else (1,0,0,1,0,0)
                    a,b,c,d,_,_=pm; det=a*d-b*c
                    if abs(det)<1e-9: raise ValueError(f"{aname} / Frame {frame} / Part {pi}: 父节点变换不可逆。")
                    wx,wy=float(dx),-float(dy); lx=(d*wx-c*wy)/det; ly=(-b*wx+a*wy)/det
                    oldx=float(rr.local.get("x",0)); oldy=float(rr.local.get("y",0)); newx=oldx+lx; newy=oldy+ly
                    FrameEditorWindow._patch_key(None,bdata,xk,newx)
                    FrameEditorWindow._patch_key(None,bdata,yk,newy)
                    report.append({"animation":aname,"frame":frame,"part_index":pi,"part_name":rr.part_name,"cell_id":rr.cell_id,"old_position":{"x":oldx,"y":oldy},"new_position":{"x":newx,"y":newy},"screen_delta":{"x":dx,"y":dy}})
            out=Path(outdir); out.mkdir(parents=True,exist_ok=True)
            target_uexp=out/app.resource.uexp.name; target_uasset=out/app.resource.uasset.name
            target_uexp.write_bytes(bytes(bdata))
            if app.resource.uasset.resolve()!=target_uasset.resolve(): target_uasset.write_bytes(app.resource.uasset.read_bytes())
            names,check_anims=te.parse_animations(target_uasset,target_uexp)
            for item in report:
                ca=next((a for a in check_anims if a["name"]==item["animation"] and a.get("header_type")!="Setup"),None)
                if ca is None: raise ValueError(f"保存后无法重新解析动画 {item['animation']}")
                attrs=te.attr_map(ca["parts"][item["part_index"]])
                if not FrameEditorWindow.exact_key(attrs.get("Posx"),item["frame"]) or not FrameEditorWindow.exact_key(attrs.get("Posy"),item["frame"]):
                    raise ValueError(f"保存后无法重新解析 {item['animation']} Frame {item['frame']} Part {item['part_index']} 的位置关键帧")
            summary={"operation":"batch_edit_animation_frame_positions","resource":app.resource.stem,"edited_key_count":len(report),"edited_frames":len(grouped),"edits":report,"output_uexp":str(target_uexp),"same_uexp_size":len(bdata)==app.resource.uexp.stat().st_size,"runtime_game_tested":False}
            (out/"animation_frame_position_edit_report.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
            app._recorded_frame_edits.clear()
            messagebox.showinfo(app.T("title"),f"已批量写入 {len(report)} 个切片位置，覆盖 {len(grouped)} 个动画帧，并通过重新解析检查。\n输出：{target_uexp}\n\n尚未进行游戏内验证。")
        except Exception as e:
            messagebox.showerror(app.T("title"),f"批量写入失败：{e}\n请检查输出目录中的文件，不要直接用于游戏内测试。")

    def save(self):
        if not self._pending_deltas:messagebox.showinfo(self.title(),"没有待保存的位置修改。",parent=self);return
        pending_parts=list(self._pending_deltas)
        if not self._frame_editable_for_parts(self.frame,pending_parts):
            count=self._frame_count(); candidates=[f for f in range(count) if self._frame_editable_for_parts(f,pending_parts)]
            if candidates:
                new=min(candidates,key=lambda f:(abs(f-self.frame),f)); old=self.frame; self.frame=new; self.title(f"编辑动画帧 - {self.anim_name} / Frame {new}"); self.render()
                messagebox.showwarning(self.title(),f"原 Frame {old} 无法安全保存所有已修改切片。已自动跳转到最近的共同可保存帧 Frame {new}，临时位移已保留。请确认预览后再次点击保存。",parent=self);return
            messagebox.showerror(self.title(),"未找到能同时保存所有已修改切片的共同精确关键帧。临时修改仍保留，请撤销部分切片或逐次保存。",parent=self);return
        anim=core.animation_by_name(self.data,self.anim_name); bdata=bytearray(self.resource.uexp.read_bytes()); report_parts=[]
        try:
            states=te.make_frame_state(anim,self.frame,self.data["static_map"]); worlds=te.world_matrices(states)
            rows_by_part={r.part_index:r for r in self.rows}
            for pi,(dx,dy) in self._pending_deltas.items():
                if pi not in rows_by_part:raise ValueError(f"当前帧中找不到已修改的 Part {pi}；请跳转到包含该切片的帧后再保存。")
                r=rows_by_part[pi]; part=anim["parts"][pi]; attrs=te.attr_map(part); xk=self.exact_key(attrs.get("Posx"),self.frame); yk=self.exact_key(attrs.get("Posy"),self.frame)
                if not xk or not yk:raise ValueError(f"Part {pi} 缺少当前帧 Posx/Posy 精确关键帧")
                pm=worlds.get(r.parent_id,(1,0,0,1,0,0)) if r.parent_id is not None else (1,0,0,1,0,0)
                a,b,c,d,_,_=pm; det=a*d-b*c
                if abs(det)<1e-9:raise ValueError(f"Part {pi} 的父节点变换矩阵不可逆")
                wx,wy=dx,-dy; lx=(d*wx-c*wy)/det; ly=(-b*wx+a*wy)/det
                oldx=float(r.local.get("x",0)); oldy=float(r.local.get("y",0)); newx=oldx+lx; newy=oldy+ly
                self._patch_key(bdata,xk,newx); self._patch_key(bdata,yk,newy)
                report_parts.append({"part_index":pi,"part_name":r.part_name,"cell_id":r.cell_id,"old_position":{"x":oldx,"y":oldy},"new_position":{"x":newx,"y":newy},"screen_delta":{"x":dx,"y":dy}})
        except Exception as e:messagebox.showerror(self.title(),f"准备写入失败：{e}",parent=self);return
        outdir=filedialog.askdirectory(parent=self,title="选择保存修改后 UEXP 的输出目录")
        if not outdir:return
        out=Path(outdir);out.mkdir(parents=True,exist_ok=True)
        try:
            target_uexp=out/self.resource.uexp.name;target_uasset=out/self.resource.uasset.name
            target_uexp.write_bytes(bytes(bdata))
            if self.resource.uasset.resolve()!=target_uasset.resolve():target_uasset.write_bytes(self.resource.uasset.read_bytes())
            names,check_anims=te.parse_animations(target_uasset,target_uexp);ca=next(a for a in check_anims if a["name"]==self.anim_name and a.get("header_type")!="Setup")
            for item in report_parts:
                cp=ca["parts"][item["part_index"]];cm=te.attr_map(cp)
                if not self.exact_key(cm.get("Posx"),self.frame) or not self.exact_key(cm.get("Posy"),self.frame):raise ValueError(f"保存后无法重新解析 Part {item['part_index']} 的位置关键帧")
            report={"operation":"edit_animation_frame_positions","resource":self.resource.stem,"animation":self.anim_name,"frame":self.frame,"edited_parts":report_parts,"output_uexp":str(target_uexp),"same_uexp_size":len(bdata)==self.resource.uexp.stat().st_size,"runtime_game_tested":False}
            (out/"animation_frame_position_edit_report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
            messagebox.showinfo(self.title(),f"已保存 {len(report_parts)} 个切片的位置，并通过 UEXP 重新解析检查。\n输出：{target_uexp}\n\n尚未进行游戏内验证。",parent=self)
            self._pending_deltas.clear();self.render()
        except Exception as e:messagebox.showerror(self.title(),f"保存文件后验证失败，请不要在游戏中使用此输出。\n{e}",parent=self)

if __name__=="__main__":
    app=App(); app.mainloop()
