"""Graphical pack manager for the pyOCD global cache (inject).

Fixed pixel sizes (tk scales fonts automatically once the process is
DPI aware), per-column filter row, drag & drop of .pack files.

Run with:  ppi gui   (or: python -m pyocd_pack_inject gui)
GUI extras are an optional dependency: pip install "pyocd-pack-inject[gui]"
"""

from __future__ import annotations

import ctypes
import os
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
import tkinter.messagebox as messagebox
import tkinter.ttk as ttk
import webbrowser

from . import (HELP_URL, __appname__, __author__, __copyright__,
               __version__)
from .devices_dialog import DevicesDialog
from .manager import PackManager, PackManagerError

# --- HiDPI helpers ---
DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)


def enable_dpi_awareness() -> None:
    """Per-monitor DPI aware before Tk() (falls back gracefully).

    Once DPI aware, Tk sizes fonts automatically; pixel sizes below stay
    identical across dialogs.
    """
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(
            DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)
        return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


try:
    from tksheet import Sheet
except ImportError:  # pragma: no cover
    Sheet = None

try:
    import windnd
except ImportError:  # pragma: no cover
    windnd = None


def _require_gui_extras() -> None:
    missing = []
    if Sheet is None:
        missing.append("tksheet")
    if windnd is None:
        missing.append("windnd")
    if missing:
        raise PackManagerError(
            "missing GUI dependency: %s. Run: pip install "
            "'pyocd-pack-inject[gui]'" % " and ".join(missing))


class PackInjectApp(tk.Tk):
    """List injected packs (per-column filters, drag & drop install,
    remove selected)."""

    # (key, title, width) - 360:360:160 column width proportion.
    COLS = [('vendor', 'Vendor', 360), ('pack', 'Pack', 360),
            ('version', 'Version', 160)]

    def __init__(self, data_path: str | None = None):
        enable_dpi_awareness()
        _require_gui_extras()
        super().__init__()
        self.title("pyocd-pack-inject - Pack Manager")
        self._mgr = PackManager(data_path=data_path)
        self._build_menu()
        self._all = []          # [(PackMeta, path)] unfiltered
        self._shown = []        # [(PackMeta, path)] after filter
        self._hl_row = None
        self._filter_after = None
        self._last_dir = None   # remember the dialog directory across Adds

        self.resizable(False, False)
        self.withdraw()

        self._build_ui()
        # First paint: actually load installed packs.
        self.refresh(first=True)
        # Warm the ~30 MB index cache in the background so the first Add
        # does not stall on a cold read of index.json.
        threading.Thread(target=self._mgr._load_index, daemon=True).start()

        self.update_idletasks()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        self.geometry('%dx%d+%d+%d' % (w, h,
            (self.winfo_screenwidth() - w) // 2,
            (self.winfo_screenheight() - h) // 3))
        self.minsize(w, h)
        self.deiconify()
        self.protocol('WM_DELETE_WINDOW', self._close)
        # Drag & drop .pack files anywhere on the window.
        windnd.hook_dropfiles(self, func=self._on_drop_files)

    # ---------------- menu ----------------

    def _build_menu(self) -> None:
        menubar = tk.Menu(self)
        menubar.add_command(label='Help', command=self._show_help)
        menubar.add_command(label='About', command=self._show_about)
        self.config(menu=menubar)

    def _show_help(self) -> None:
        # Open the project README (opens the project README).
        webbrowser.open(HELP_URL, new=0)

    def _show_about(self) -> None:
        show_about = (
            __appname__ + '\r\n\r\n' +
            'Version:%s\r\n' % __version__ +
            'Author:%s\r\n' % __author__ +
            'Copyright@%s\r\n\r\n' % __copyright__ +
            'pyOCD %s\r\n' % self._pyocd_version() +
            'Cache: %s' % self._mgr.data_path
        )
        messagebox.showinfo(title='About', message=show_about, parent=self)

    @staticmethod
    def _pyocd_version() -> str:
        try:
            import pyocd
            return getattr(pyocd, '__version__', '?') or '?'
        except Exception:
            return '?'

    # ---------------- UI ----------------

    def _build_ui(self) -> None:
        cols = self.COLS

        # Bottom button row.
        btn_frame = tk.Frame(self)
        close_btn = ttk.Button(btn_frame, text='Close', width=10,
                               command=self._close)
        remove_btn = ttk.Button(btn_frame, text='Remove', width=10,
                                command=self.remove_selected)
        add_btn = ttk.Button(btn_frame, text='Add...', width=10,
                             command=self.install_files)
        sep_bottom = tk.Frame(self, height=1, bg='#c0c0c0')
        sep_bottom.pack(side='bottom', fill='x')
        btn_frame.pack(side='bottom', fill='x', padx=(6, 3), pady='3p')
        for b in (add_btn, remove_btn, close_btn):
            b.pack(side='right', padx='3p', pady=0)

        # Table area: header / separator / filter / separator / sheet.
        mid = tk.Frame(self, bg='white')
        head_frame = tk.Frame(mid, bg='white')
        filter_frame = tk.Frame(mid, bg='white')
        self.entries = {}
        for i, (key, title, w) in enumerate(cols):
            c = i * 2
            lw = w if i == len(cols) - 1 else w - 1
            head_frame.columnconfigure(c, minsize=lw)
            tk.Label(head_frame, text=title, anchor='w', bg='white'
                     ).grid(row=0, column=c, sticky='ew')
            if i < len(cols) - 1:
                head_frame.columnconfigure(c + 1, minsize=1)
                tk.Frame(head_frame, width=1, bg='#e1e1e1'
                         ).grid(row=0, column=c + 1, sticky='ns')
            filter_frame.columnconfigure(i, minsize=w)
            e = tk.Entry(filter_frame, width=8)
            e.grid(row=0, column=i, sticky='ew')
            self.entries[key] = e

        # Fixed-height sheet; external scrollbar (always visible).
        sheet = Sheet(mid, height=720, show_row_index=False,
                      show_header=False,
                      auto_resize_columns=False, auto_resize_rows=False,
                      show_x_scrollbar=False, show_y_scrollbar=False,
                      column_drag_and_drop=False, row_drag_and_drop=False)
        sheet.enable_bindings('mousewheel', 'cell_select', 'row_select',
                              'single_select', 'select', 'deselect',
                              'arrowkeys', 'copy')
        sheet.set_options(font=('', 8, ''), empty_vertical=0,
                          table_selected_rows_bg='#cce4f7')
        sheet.default_row_height(36)

        mid.columnconfigure(0, weight=1)
        mid.columnconfigure(1, minsize=20)
        mid.rowconfigure(4, weight=1)

        sep_top = tk.Frame(self, height=1, bg='#e1e1e1')
        sep_top.pack(side='top', fill='x', padx=(6, 0))
        mid.pack(fill='both', expand=True, side='top', padx=(6, 0), pady=(4, '4p'))
        tk.Frame(mid, height=1, bg='#e1e1e1').grid(row=1, column=0, sticky='ew')
        tk.Frame(mid, height=1, bg='#e1e1e1').grid(row=3, column=0, sticky='ew')
        head_frame.grid(row=0, column=0, sticky='ew')
        filter_frame.grid(row=2, column=0, sticky='ew')
        sheet.grid(row=4, column=0, sticky='nsew')

        # Always-visible external vertical scrollbar (fixed, always visible).
        ext_sb = tk.Scrollbar(mid, orient='vertical',
                              command=sheet.MT._yscrollbar, width="12p")
        sheet.MT.configure(yscrollcommand=ext_sb.set)
        ext_sb.grid(row=0, column=1, rowspan=5, sticky='ns')

        self.sheet = sheet
        self.ext_sb = ext_sb
        for e in self.entries.values():
            e.bind('<KeyRelease>', self._on_filter_key)
        sheet.bind('<Double-Button-1>', self._on_double)
        self.bind('<ButtonPress-1>', self._on_press)
        self.bind('<Escape>', lambda ev: self._close())

    # ---------------- data ----------------

    def refresh(self, first=False) -> None:
        self._all = self._mgr.list_installed()
        self._apply_filter(first=first)

    def _apply_filter(self, first=False) -> None:
        kws = {k: e.get().strip().lower() for k, e in self.entries.items()}
        shown = []
        for meta, path in self._all:
            if (kws['vendor'] in meta.vendor.lower()
                    and kws['pack'] in meta.pack.lower()
                    and kws['version'] in meta.version.lower()):
                shown.append((meta, path))
        self._shown = shown
        widths = {k: w for k, t, w in self.COLS}
        data = [[self._fit(meta.vendor, widths['vendor']),
                 self._fit(meta.pack, widths['pack']),
                 self._fit(meta.version, widths['version'])]
                for meta, path in shown]
        if not data:
            data = [['', '', '']]
        self.sheet.set_sheet_data(data, reset_col_positions=first,
                                  reset_row_positions=True)
        for i, (k, t, w) in enumerate(self.COLS):
            self.sheet.column_width(i, w)
        self._hl_row = None

    def _fit(self, text, width):
        """Truncate long cell text with an ellipsis ."""
        if not hasattr(self, '_cell_font'):
            self._cell_font = tkfont.Font(family='Segoe UI', size=9)
        f = self._cell_font
        s = str(text)
        if f.measure(s) <= width:
            return s
        lo, hi = 0, len(s)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if f.measure(s[:mid] + '...') <= width:
                lo = mid
            else:
                hi = mid - 1
        return s[:lo] + '...' if lo > 0 else '...'

    def _current_row(self):
        row = self._hl_row
        if row is None:
            sel = self.sheet.get_currently_selected()
            if sel and sel[0] is not None and 0 <= sel[0] < len(self._shown):
                row = sel[0]
        if row is None or not (0 <= row < len(self._shown)):
            return None
        return row

    # ---------------- actions ----------------

    def install_files(self, paths=None) -> None:
        if paths is None:
            from tkinter import filedialog
            paths = filedialog.askopenfilenames(
                title='Add pack files',
                initialdir=self._last_dir,
                filetypes=[('CMSIS Pack', '*.pack'), ('All files', '*.*')])
        if not paths:
            return
        try:
            self._last_dir = os.path.dirname(str(paths[0]))
        except (TypeError, IndexError):
            pass
        # Run the install off the UI thread (index.json read/write can take
        # a few hundred ms); show a busy cursor and refresh when done.
        self.configure(cursor='watch')
        threading.Thread(target=self._install_bg, args=(list(paths),),
                         daemon=True).start()

    def _install_bg(self, paths) -> None:
        try:
            metas, failures = self._mgr.install_many(paths)
        except Exception as e:
            metas, failures = [], [("", str(e))]
        ok = [m.full_ref for m in metas]
        self.after(0, lambda: self._install_done(ok, failures))

    def _install_done(self, ok, fail) -> None:
        self.configure(cursor='')
        self.refresh()
        if fail:
            msg = 'Failed to add %d pack(s):\n' % len(fail)
            msg += '\n'.join('  %s: %s' % pair for pair in fail[:5])
            messagebox.showwarning('Add Pack', msg, parent=self)

    def _on_drop_files(self, files) -> None:
        """windnd callback: install dropped .pack files."""
        paths = []
        for raw in files:
            p = raw.decode('utf-8', errors='replace') if isinstance(raw, bytes) else raw
            paths.append(p)
        if paths:
            self.install_files(paths)

    def remove_selected(self) -> None:
        row = self._current_row()
        if row is None:
            return
        meta, path = self._shown[row]
        if not messagebox.askokcancel(
                'Remove Pack',
                'Remove %s from the global cache?' % meta.full_ref,
                parent=self):
            return
        try:
            self._mgr.remove(meta.vendor, meta.pack, meta.version)
        except Exception as e:
            messagebox.showwarning('Remove Pack',
                                   'Failed to remove pack:\n%s' % e, parent=self)
            return
        self.refresh()

    # ---------------- interaction ----------------

    def _on_filter_key(self, event=None):
        if self._filter_after:
            self.after_cancel(self._filter_after)
        self._filter_after = self.after(60, lambda: self._apply_filter())

    def _on_press(self, event=None) -> None:
        w = event.widget
        is_sheet = False
        while w is not None:
            if w is self.sheet:
                is_sheet = True
                break
            w = getattr(w, 'master', None)
        if is_sheet:
            row = self.sheet.identify_row(event)
            if row is not None and row < len(self._shown):
                self.sheet.dehighlight_all()
                self.sheet.highlight_rows(row, bg='#cce4f7')
                self._hl_row = row
            else:
                self._gray()
        else:
            self._gray()

    def _gray(self) -> None:
        self.sheet.deselect()
        if self._hl_row is not None:
            self.sheet.dehighlight_all()
            self.sheet.highlight_rows(self._hl_row, bg='#e6e6e6')

    def _on_double(self, event=None) -> None:
        """Double-click a pack: show the devices/chips it provides."""
        row = self.sheet.identify_row(event)
        if row is None or row >= len(self._shown):
            return
        self._hl_row = row
        meta, path = self._shown[row]
        # Parse may take a few hundred ms; show a busy cursor meanwhile.
        try:
            self.configure(cursor='watch')
            self.update_idletasks()
            DevicesDialog(self, path, meta.full_ref)
        finally:
            self.configure(cursor='')

    def _close(self):
        if self._filter_after:
            self.after_cancel(self._filter_after)
        self.destroy()


def main(data_path: str | None = None) -> int:
    try:
        app = PackInjectApp(data_path=data_path)
    except PackManagerError as e:
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror('pyocd-pack-inject', str(e), parent=root)
            root.destroy()
        except Exception:
            print("error: %s" % e, file=sys.stderr)
        return 1
    app.mainloop()
    return 0


if __name__ == '__main__':
    sys.exit(main())
