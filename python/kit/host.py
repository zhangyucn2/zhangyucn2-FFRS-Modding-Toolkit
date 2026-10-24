"""把各个工具嵌进标签页的适配层。

两种嵌入方式：

1. 工具原本是 `class App:` + `self.root = tk.Tk()`  → 传入 `Host` 作为 root
2. 工具原本是 `class App(tk.Tk):`                    → 改成 `class App(WindowMixin, tk.Frame)`

`Host` 和 `WindowMixin` 都只实现工具真正用到的那一小撮窗口 API
（title / geometry / minsize / protocol / after / update / mainloop …），
其余一律转发给底层 Frame，所以工具内部的控件代码完全不用改。
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk


class WindowMixin:
    """给 `class App(tk.Frame)` 提供 Tk 窗口 API 的转发。"""

    _win: tk.Misc
    _own: bool = False

    # --- 供子类 __init__ 调用 ---
    def _bind_window(self, master, title: str = ""):
        if master is None:
            self._own = True
            self._win = tk.Tk()
            parent = self._win
        else:
            self._own = False
            self._win = master.winfo_toplevel()
            parent = master
        super().__init__(parent)
        self.pack(fill="both", expand=True)
        if title:
            try:
                self._win.title(title)
            except Exception:
                pass
        return parent

    # --- 窗口 API 转发 ---
    def title(self, value=None):
        if value is not None and not self._own:
            return ""          # 嵌入模式由 Toolkit 决定标题
        try:
            return self._win.title() if value is None else self._win.title(value)
        except Exception:
            return ""

    def geometry(self, value=None):
        if not self._own:          # 嵌入模式下由 Toolkit 统一决定窗口大小
            return ""
        try:
            return self._win.geometry(value) if value else self._win.geometry()
        except Exception:
            return ""

    def minsize(self, *a):
        if not self._own:
            return None
        try:
            return self._win.minsize(*a)
        except Exception:
            return None

    def maxsize(self, *a):
        try:
            return self._win.maxsize(*a)
        except Exception:
            return None

    def resizable(self, *a):
        try:
            return self._win.resizable(*a)
        except Exception:
            return None

    def protocol(self, name, func=None):
        if self._own:
            try:
                return self._win.protocol(name, func)
            except Exception:
                return None
        return None

    def iconbitmap(self, *a, **k):
        return None

    def attributes(self, *a, **k):
        return None

    def state(self, *a):
        return None

    def wm_state(self, *a):
        return None

    def after(self, *a, **k):
        return self._win.after(*a, **k)

    def update_idletasks(self):
        return self._win.update_idletasks()

    def update(self):
        return self._win.update()

    def mainloop(self, *a, **k):
        if self._own:
            return self._win.mainloop(*a, **k)
        return None

    def destroy(self):
        try:
            super().destroy()
        finally:
            if self._own:
                try:
                    self._win.destroy()
                except Exception:
                    pass

    def config(self, cnf=None, **kw):
        if "menu" in kw:
            m = kw.pop("menu")
            if self._own:
                try:
                    self._win.config(menu=m)
                except Exception:
                    pass
        return super().config(cnf, **kw)

    configure = config


class Host(WindowMixin, tk.Frame):
    """独立工具（`self.root` 型）的嵌入式宿主。"""

    def __init__(self, master, title: str = ""):
        self._bind_window(master, title)


class ScrollPage(tk.Frame):
    """内容超高才出滚动条；够大时内容铺满整页。"""

    def __init__(self, master):
        super().__init__(master)
        self._need_scroll = False
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0)
        self.vsb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas)
        self._wid = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.vsb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner.bind("<Configure>", lambda e: self._sync())
        self.canvas.bind("<Configure>", lambda e: self._sync())
        self.canvas.bind("<Enter>", lambda e: self.canvas.bind_all("<MouseWheel>", self._wheel))
        self.canvas.bind("<Leave>", lambda e: self.canvas.unbind_all("<MouseWheel>"))

    def _sync(self):
        try:
            bbox = self.canvas.bbox("all")
            need_h = (bbox[3] - bbox[1]) if bbox else 0
            view_h = self.canvas.winfo_height() or 1
            view_w = self.canvas.winfo_width() or 1
            self.canvas.itemconfigure(self._wid, width=view_w)
            self._need_scroll = need_h > view_h + 2
            if self._need_scroll:
                if not self.vsb.winfo_ismapped():
                    self.vsb.pack(side="right", fill="y")
                self.canvas.itemconfigure(self._wid, height=need_h)
            else:
                if self.vsb.winfo_ismapped():
                    self.vsb.pack_forget()
                self.canvas.itemconfigure(self._wid, height=view_h)
                self.canvas.yview_moveto(0)
        except Exception:
            pass

    def _wheel(self, e):
        if not self._need_scroll:
            return
        try:
            self.canvas.yview_scroll(int(-e.delta / 120), "units")
        except Exception:
            pass
