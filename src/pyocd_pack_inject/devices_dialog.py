"""Per-pack device list dialog (shown on double-click in the pack list).

Layout mirrors dap_download's target_picker.py: fixed header row,
per-column filter boxes, tksheet body with an always-visible external
scrollbar, and OK/Cancel buttons. Columns show a friendly device name,
the normalised target name pyOCD/CLI actually accepts, and the flash size.
OK / double-click copies the selected target name to the clipboard.
"""

from __future__ import annotations

import tkinter as tk
import tkinter.messagebox as messagebox
import tkinter.ttk as ttk

try:
    from tksheet import Sheet
except ImportError:  # pragma: no cover
    Sheet = None

from .manager import PackManagerError


def _normalise(name: str) -> str:
    from pyocd.target import normalise_target_type_name
    return normalise_target_type_name(name)


def _fmt_flash(size: int) -> str:
    if size <= 0:
        return '-'
    if size >= 1024 * 1024:
        return '%.0fM' % (size / 1024 / 1024)
    return '%dK' % (size // 1024)


def list_pack_devices(pack_path: str):
    """Parse a .pack and yield (device, target, flash) rows.

    device: friendly part number without the leading '-' the CMSIS DFP uses.
    target: normalised target type name usable with `pyocd -t` / GUI.
    flash : size of the largest flash region, formatted.
    """
    from pyocd.target.pack.cmsis_pack import CmsisPack

    pack = CmsisPack(pack_path)
    rows = []
    for dev in pack.devices:
        part = getattr(dev, 'part_number', None) or ''
        flashes = [r for r in getattr(dev, 'memory_map', [])
                   if getattr(r, 'is_flash', False)]
        flash = max((r.length for r in flashes), default=0)
        device = part.lstrip('-')
        rows.append((device or part, _normalise(part), _fmt_flash(flash)))
    rows.sort(key=lambda r: r[0].lower())
    return rows


class DevicesDialog(tk.Toplevel):
    """List the chips supported by one injected pack."""

    COLS = [('device', 'Device', 360), ('target', 'Target', 360),
            ('flash', 'Flash Size', 160)]

    def __init__(self, master, pack_path: str, pack_title: str):
        super().__init__(master)
        self.title('Devices - %s' % pack_title)
        self.transient(master)
        self.resizable(False, False)
        self.withdraw()
        self._rows = []
        self._shown = []
        self._hl_row = None
        self._filter_after = None

        try:
            self._all = list_pack_devices(pack_path)
        except Exception as e:
            self.destroy()
            messagebox.showwarning('Devices',
                                   'Failed to read pack:\n%s' % e, parent=master)
            return

        self._build_ui()
        self._apply_filter(first=True)

        self.update_idletasks()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        self.geometry('%dx%d+%d+%d' % (w, h,
            master.winfo_rootx() + (master.winfo_width() - w) // 2,
            master.winfo_rooty() + (master.winfo_height() - h) // 2))
        self.deiconify()
        self.grab_set()
        self.focus_set()

    # ---------------- UI (mirrors dap target_picker.py) ----------------

    def _build_ui(self) -> None:
        cols = self.COLS

        btn_frame = tk.Frame(self)
        ok_btn = ttk.Button(btn_frame, text='OK', width=10, command=self._copy)
        cancel_btn = ttk.Button(btn_frame, text='Cancel', width=10,
                                command=self._close)
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

        sheet = Sheet(mid, height=360, show_row_index=False,
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
        btn_frame.pack(side='bottom', fill='x', padx=(6, 3), pady='3p')
        ok_btn.pack(side='right', padx='3p', pady=0)
        cancel_btn.pack(side='right', padx='3p', pady=0)
        sep_bottom = tk.Frame(self, height=1, bg='#c0c0c0')
        sep_bottom.pack(side='bottom', fill='x')
        mid.pack(fill='both', expand=True, side='top', padx=(6, 0), pady=(4, '4p'))
        tk.Frame(mid, height=1, bg='#e1e1e1').grid(row=1, column=0, sticky='ew')
        tk.Frame(mid, height=1, bg='#e1e1e1').grid(row=3, column=0, sticky='ew')
        head_frame.grid(row=0, column=0, sticky='ew')
        filter_frame.grid(row=2, column=0, sticky='ew')
        sheet.grid(row=4, column=0, sticky='nsew')

        ext_sb = tk.Scrollbar(mid, orient='vertical',
                              command=sheet.MT._yscrollbar, width="12p")
        sheet.MT.configure(yscrollcommand=ext_sb.set)
        ext_sb.grid(row=0, column=1, rowspan=5, sticky='ns')

        self.sheet = sheet
        for e in self.entries.values():
            e.bind('<KeyRelease>', self._on_filter_key)
        sheet.bind('<Double-Button-1>', self._copy)
        self.bind('<ButtonPress-1>', self._on_press)
        self.protocol('WM_DELETE_WINDOW', self._close)

    # ---------------- data ----------------

    def _apply_filter(self, first=False) -> None:
        kws = {k: e.get().strip().lower() for k, e in self.entries.items()}
        shown = []
        for row in self._all:
            device, target, flash = row
            if (kws['device'] in device.lower()
                    and kws['target'] in target.lower()
                    and kws['flash'] in flash.lower()):
                shown.append(row)
        self._shown = shown
        data = list(shown)
        if not data:
            data = [['', '', '']]
        self.sheet.set_sheet_data(data, reset_col_positions=first,
                                  reset_row_positions=True)
        widths = {k: w for k, t, w in self.COLS}
        for i, (k, t, w) in enumerate(self.COLS):
            self.sheet.column_width(i, w)
        self._hl_row = None

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

    def _copy(self, event=None) -> None:
        """Copy the selected target name to the clipboard and close."""
        row = self._current_row()
        if row is None:
            return
        target = self._shown[row][1]
        self.clipboard_clear()
        self.clipboard_append(target)
        self._close()

    def _close(self):
        if self._filter_after:
            self.after_cancel(self._filter_after)
        self.destroy()

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
