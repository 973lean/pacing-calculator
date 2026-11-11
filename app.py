"""
Speech & Script Pacing Calculator
=================================

A small bidirectional calculator for video editors, voice actors and
scriptwriters. Pick which value to solve for (WPM, Word Count or Duration);
that field becomes the locked, highlighted result, the other two are inputs.

    WPM        = Word Count / Duration
    Word Count = Duration * WPM
    Duration   = Word Count / WPM

Duration is entered as separate minutes and seconds; seconds of 60 or more
roll over into minutes when you leave the field or press Enter.

A pace gauge shows where the current WPM sits on the
Slow / Conversational / Fast scale.

The window is borderless (no system title bar); it has its own minimise and
close buttons and can be dragged from anywhere on the background.

Standard library only (tkinter). Package into a single executable with:

    pyinstaller --onefile --windowed --name PacingCalculator --icon PacingCalculator.ico \\
        --add-data "PacingCalculator.ico;." app.py
"""

import re
import sys
import threading
import tkinter as tk
import webbrowser
from tkinter import font as tkfont

import updater
from version import __version__

# --------------------------------------------------------------------------- #
# Design tokens
# --------------------------------------------------------------------------- #
WINDOW_WIDTH = 480        # height is computed from the content
WORKSPACE_MIN = (420, 400)  # smallest the Workspace can be resized to
GRIP = 7                  # width of the invisible resize edges, in px
PAD = 30                  # outer margin

BG = "#F6F7F9"            # window background
SURFACE = "#FFFFFF"       # input background
BORDER = "#E2E5EA"        # resting input border
OUTLINE = "#D5D9E0"       # 1px window outline (borderless window needs an edge)
TEXT = "#111827"          # primary text
MUTED = "#6B7280"         # labels
FAINT = "#9CA3AF"         # window controls, gauge captions
ACCENT = "#4F46E5"        # indigo accent
ACCENT_HOVER = "#4338CA"
ACCENT_SOFT = "#EEF0FE"   # result field background
ERROR = "#DC2626"
CLOSE_HOVER = "#E5484D"
SEG_BG = "#E9EBEF"        # segmented control track
CTRL_HOVER = "#E9EBEF"

# Pace gauge zones: (start WPM, end WPM, colour, caption)
GAUGE_MIN, GAUGE_MAX = 80, 220
GAUGE_ZONES = [
    (GAUGE_MIN, 130, "#E0E3FC", "Slow"),
    (130, 160, "#C3C8F8", "Conversational"),
    (160, GAUGE_MAX, "#A3AAF3", "Fast"),
]

MODE_WPM = "wpm"
MODE_WORDS = "words"
MODE_DURATION = "duration"

ERROR_INVALID = "Please enter valid numbers."
ERROR_ZERO = "Value must be greater than 0"


# --------------------------------------------------------------------------- #
# Pure helper functions (no Tkinter, easy to test)
# --------------------------------------------------------------------------- #
def parse_duration(minutes_text: str, seconds_text: str) -> float:
    """
    Total seconds from separate minutes / seconds text. A blank box counts as 0,
    but at least one must be filled. Raises ValueError on bad or negative input.
    """
    m_text, s_text = minutes_text.strip(), seconds_text.strip()
    if not m_text and not s_text:
        raise ValueError("empty duration")
    minutes = float(m_text) if m_text else 0.0
    seconds = float(s_text) if s_text else 0.0
    if minutes < 0 or seconds < 0:
        raise ValueError("negative duration")
    return minutes * 60 + seconds


def count_words(text: str) -> int:
    """Count words: whitespace-separated chunks containing a letter or digit."""
    return sum(1 for token in text.split() if re.search(r"\w", token))


def split_seconds(total_seconds: float) -> tuple:
    """125 -> (2, 5): whole minutes and leftover seconds (rounded to whole seconds)."""
    return divmod(int(round(total_seconds)), 60)


def pace_profile(wpm: float) -> str:
    """Return a human-readable pacing profile for a words-per-minute value."""
    if wpm < 130:
        return "Slow / Audiobook"
    if wpm <= 160:
        return "Conversational"
    return "Fast / Energetic"


def parse_int(text: str) -> int:
    """Parse a whole number. Raises ValueError on empty / non-numeric input."""
    return int(text.strip())


def parse_float(text: str) -> float:
    """Parse a decimal number. Raises ValueError on empty / non-numeric input."""
    return float(text.strip())


def resource_path(name: str) -> str:
    """Path to a bundled file, both when run as a script and as a PyInstaller exe."""
    import os
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def enable_windows_dpi_awareness() -> None:
    """Render crisp (non-blurry) text on high-DPI Windows displays."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:  # older Windows or non-standard setup: just skip
        pass


# --------------------------------------------------------------------------- #
# Application
# --------------------------------------------------------------------------- #
class PacingCalculatorApp:
    """Main window and all UI behaviour."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Pacing Calculator")   # still used by the taskbar / Alt+Tab
        self.root.configure(bg=OUTLINE)
        self.root.resizable(False, False)
        self.root.overrideredirect(True)       # remove the system title bar
        try:
            self.root.iconbitmap(resource_path("PacingCalculator.ico"))  # taskbar icon
        except tk.TclError:
            pass  # icon file missing or unsupported platform: keep the default

        # Scale pixel sizes with the display DPI (1.0 at 100%, 1.5 at 150%, ...)
        self.scale = max(1.0, root.winfo_fpixels("1i") / 96.0)
        self._setup_fonts()

        # Tk variables backing each widget
        self.mode = tk.StringVar(value=MODE_WPM)
        self.words_var = tk.StringVar()
        self.dur_min_var = tk.StringVar()
        self.dur_sec_var = tk.StringVar()
        self.wpm_var = tk.StringVar()
        self.duration_hint = tk.StringVar()
        self.pace_hint = tk.StringVar()
        self.error_text = tk.StringVar()

        self._drag_offset = (0, 0)
        self._ws_size = None      # last Workspace size (w, h), restored on return
        self._resize_start = None
        self._build_ui()
        self._place_window()

        # Live hints / gauge update as the user types (or as results are written)
        self.dur_min_var.trace_add("write", self._update_duration_hint)
        self.dur_sec_var.trace_add("write", self._update_duration_hint)
        self.wpm_var.trace_add("write", self._update_pace_hint)

        # Keyboard: Enter calculates, Escape closes
        self.root.bind("<Return>", lambda _e: self.calculate())
        self.root.bind("<KP_Enter>", lambda _e: self.calculate())
        self.root.bind("<Escape>", lambda _e: self.root.destroy())

        self._on_mode_change()  # apply initial field states

        # Borderless windows are hidden from the Windows taskbar by default
        self.root.after(10, self._show_in_taskbar)

        # Quietly check GitHub for a newer release shortly after launch
        self._update_info = None    # (version, download_url) when available
        self._updating = False
        self.root.after(1500, lambda: self.check_for_updates(manual=False))

    # ----------------------------------------------------------------- setup
    def _px(self, value: float) -> int:
        """Scale a pixel measurement for the current display DPI."""
        return int(round(value * self.scale))

    def _setup_fonts(self) -> None:
        """Pick a clean system font: Segoe UI (Windows), SF (macOS), else default."""
        families = set(tkfont.families(self.root))
        for name in ("Segoe UI", "SF Pro Text", "Helvetica Neue", "Inter", "DejaVu Sans"):
            if name in families:
                family = name
                break
        else:
            family = tkfont.nametofont("TkDefaultFont").actual("family")
        self.family = family

        self.f_label = tkfont.Font(family=family, size=10)
        self.f_hint = tkfont.Font(family=family, size=10)
        self.f_entry = tkfont.Font(family=family, size=15)
        self.f_seg = tkfont.Font(family=family, size=11)
        self.f_seg_on = tkfont.Font(family=family, size=11, weight="bold")
        self.f_button = tkfont.Font(family=family, size=12, weight="bold")
        self.f_ctrl = tkfont.Font(family=family, size=11)
        self.f_gauge = tkfont.Font(family=family, size=8)
        self.f_body = tkfont.Font(family=family, size=11)
        self.f_stat = tkfont.Font(family=family, size=13, weight="bold")

    def _place_window(self) -> None:
        """Size the window to its content and centre it on screen."""
        self.root.update_idletasks()
        w = self._px(WINDOW_WIDTH)
        h = self.shell.winfo_reqheight() + 2  # +2 for the 1px outline
        x = (self.root.winfo_screenwidth() - w) // 2
        y = (self.root.winfo_screenheight() - h) // 3
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    def _fit_height(self) -> None:
        """Snap to the calculator's fixed size (also used when the banner appears)."""
        if self.view == "work":
            return  # the Workspace keeps whatever size the user gave it
        self.root.update_idletasks()
        h = self.shell.winfo_reqheight() + 2
        self.root.geometry(f"{self._px(WINDOW_WIDTH)}x{h}+{self.root.winfo_x()}+{self.root.winfo_y()}")

    def _build_ui(self) -> None:
        """Create and lay out every widget using grid()."""
        # 1px outline around a full-size background frame
        self.shell = tk.Frame(self.root, bg=BG)
        self.shell.grid(row=0, column=0, sticky="nsew", padx=1, pady=1)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        self.shell.columnconfigure(0, weight=1)
        self._make_draggable(self.shell)

        # Window controls (top-right, no title text) -----------------------
        bar = tk.Frame(self.shell, bg=BG)
        bar.grid(row=0, column=0, sticky="ew")
        bar.columnconfigure(0, weight=1)
        self._make_draggable(bar)
        # View switcher: Calculator / Workspace (plain text tabs, top-left)
        tabs = tk.Frame(bar, bg=BG)
        tabs.grid(row=0, column=0, sticky="w", padx=(self._px(PAD - 2), 0))
        self._make_draggable(tabs)
        self._tabs = {}
        for col, (label, view) in enumerate([("Calculator", "calc"), ("Workspace", "work")]):
            tab = tk.Label(tabs, text=label, bg=BG, fg=FAINT, font=self.f_label,
                           padx=self._px(2), pady=self._px(6), cursor="hand2")
            tab.grid(row=0, column=col, padx=(0, self._px(14)))
            tab.bind("<Button-1>", lambda _e, v=view: self.show_view(v))
            self._tabs[view] = tab
        self.view = "calc"

        self._window_button(bar, 1, "—", CTRL_HOVER, MUTED, self._minimize)
        self._window_button(bar, 2, "✕", CLOSE_HOVER, "white", self.root.destroy)

        # Update banner (hidden until a newer release is found) -------------
        self.banner = tk.Frame(self.shell, bg=ACCENT_SOFT, padx=self._px(14), pady=self._px(9))
        self.banner.grid(row=1, column=0, sticky="ew",
                         padx=self._px(PAD), pady=(0, self._px(14)))
        self.banner.columnconfigure(0, weight=1)
        self.banner_text = tk.StringVar()
        tk.Label(self.banner, textvariable=self.banner_text, bg=ACCENT_SOFT, fg=TEXT,
                 font=self.f_hint).grid(row=0, column=0, sticky="w")
        self.banner_action = tk.Label(self.banner, text="Update now", bg=ACCENT_SOFT, fg=ACCENT,
                                      font=self.f_seg_on, cursor="hand2")
        self.banner_action.grid(row=0, column=1, sticky="e")
        self.banner_action.bind("<Button-1>", lambda _e: self.install_update())
        self.banner.grid_remove()

        main = tk.Frame(self.shell, bg=BG)
        main.grid(row=2, column=0, sticky="nsew",
                  padx=self._px(PAD), pady=(self._px(2), self._px(PAD - 6)))
        main.columnconfigure(0, weight=1)
        self._make_draggable(main)
        self.calc_view = main
        self.shell.rowconfigure(2, weight=1)
        self._build_workspace()

        # "Solve for" segmented control -------------------------------------
        self._label(main, "SOLVE FOR").grid(row=0, column=0, sticky="w",
                                           pady=(0, self._px(8)))
        track = tk.Frame(main, bg=SEG_BG, padx=self._px(4), pady=self._px(4))
        track.grid(row=1, column=0, sticky="ew", pady=(0, self._px(22)))
        self._segments = {}
        for col, (label, value) in enumerate(
                [("WPM", MODE_WPM), ("Word Count", MODE_WORDS), ("Duration", MODE_DURATION)]):
            track.columnconfigure(col, weight=1, uniform="seg")
            seg = tk.Label(track, text=label, bg=SEG_BG, fg=MUTED, font=self.f_seg,
                           pady=self._px(7), cursor="hand2")
            seg.grid(row=0, column=col, sticky="ew")
            seg.bind("<Button-1>", lambda _e, v=value: self._select_mode(v))
            self._segments[value] = seg

        # Fields: label + live hint on one line, input below ----------------
        self.words_entry = self._field(main, 2, "Word Count", self.words_var, None)
        self.dur_min_entry, self.dur_sec_entry = self._duration_field(main, 4)
        self.wpm_entry = self._field(main, 6, "Speech Pace (WPM)",
                                     self.wpm_var, self.pace_hint, bottom_gap=10)

        # Pace gauge diagram -------------------------------------------------
        self.gauge = tk.Canvas(main, height=self._px(46), bg=BG,
                               highlightthickness=0, bd=0)
        self.gauge.grid(row=8, column=0, sticky="ew", pady=(0, self._px(20)))
        self.gauge.bind("<Configure>", lambda _e: self._draw_gauge())

        # Calculate button (flat label so it looks the same on every OS) ----
        self.button = tk.Label(main, text="Calculate", bg=ACCENT, fg="white",
                               font=self.f_button, pady=self._px(12), cursor="hand2")
        self.button.grid(row=9, column=0, sticky="ew")
        self.button.bind("<Button-1>", lambda _e: self.calculate())
        self.button.bind("<Enter>", lambda _e: self.button.configure(bg=ACCENT_HOVER))
        self.button.bind("<Leave>", lambda _e: self.button.configure(bg=ACCENT))

        # Inline error message (fixed height so the layout never jumps)
        err = tk.Label(main, textvariable=self.error_text, bg=BG, fg=ERROR,
                       font=self.f_hint, anchor="w")
        err.grid(row=10, column=0, sticky="ew", pady=(self._px(8), 0))
        self._make_draggable(err)

        # Footer: version on the left, manual update check on the right ------
        footer = tk.Frame(main, bg=BG)
        footer.grid(row=11, column=0, sticky="ew", pady=(self._px(4), 0))
        footer.columnconfigure(0, weight=1)
        self._make_draggable(footer)
        ver = tk.Label(footer, text=f"v{__version__}", bg=BG, fg=FAINT, font=self.f_gauge)
        ver.grid(row=0, column=0, sticky="w")
        self._make_draggable(ver)
        self.update_link = tk.Label(footer, text="Check for updates", bg=BG, fg=FAINT,
                                    font=self.f_gauge, cursor="hand2")
        self.update_link.grid(row=0, column=1, sticky="e")
        self.update_link.bind("<Button-1>", lambda _e: self.check_for_updates(manual=True))
        self.update_link.bind("<Enter>", lambda _e: self.update_link.configure(fg=ACCENT))
        self.update_link.bind("<Leave>", lambda _e: self.update_link.configure(fg=FAINT))

        # Entries that become the locked result in each mode
        self._output_entry = {
            MODE_WPM: [self.wpm_entry],
            MODE_WORDS: [self.words_entry],
            MODE_DURATION: [self.dur_min_entry, self.dur_sec_entry],
        }

    # ------------------------------------------------------------ workspace
    def _build_workspace(self) -> None:
        """Script box + WPM; word count and duration update as you type.

        Shares the calculator's grid cell; show_view() raises one or the other.
        """
        work = tk.Frame(self.shell, bg=BG)
        work.grid(row=2, column=0, sticky="nsew",
                  padx=self._px(PAD), pady=(self._px(2), self._px(PAD - 6)))
        work.columnconfigure(0, weight=1)
        work.rowconfigure(0, weight=1)
        self._make_draggable(work)
        self.work_view = work

        # Script box
        box = tk.Frame(work, bg=SURFACE, highlightthickness=1,
                       highlightbackground=BORDER, highlightcolor=BORDER)
        box.grid(row=0, column=0, sticky="nsew")
        box.columnconfigure(0, weight=1)
        box.rowconfigure(0, weight=1)
        self.script = tk.Text(box, font=self.f_body, wrap="word", undo=True,
                              relief="flat", bd=0, highlightthickness=0, height=8, width=10,
                              bg=SURFACE, fg=TEXT, insertbackground=TEXT,
                              selectbackground=ACCENT_SOFT, selectforeground=TEXT,
                              padx=self._px(14), pady=self._px(12), spacing2=self._px(3))
        self.script.grid(row=0, column=0, sticky="nsew")
        self.script.bind("<FocusIn>", lambda _e: box.configure(
            highlightbackground=ACCENT, highlightcolor=ACCENT))
        self.script.bind("<FocusOut>", lambda _e: box.configure(
            highlightbackground=BORDER, highlightcolor=BORDER))
        self.script.bind("<<Modified>>", self._on_script_change)

        # Placeholder shown while the box is empty
        self.placeholder = tk.Label(box, text="Paste or type your script\u2026", bg=SURFACE,
                                    fg=FAINT, font=self.f_body, cursor="xterm")
        self.placeholder.place(x=self._px(16), y=self._px(12))
        self.placeholder.bind("<Button-1>", lambda _e: self.script.focus_set())

        # Bottom row: WPM input on the left, live stats on the right
        row = tk.Frame(work, bg=BG)
        row.grid(row=1, column=0, sticky="ew", pady=(self._px(14), 0))
        row.columnconfigure(1, weight=1)
        self._make_draggable(row)

        self.ws_wpm_var = tk.StringVar(value="150")
        self.ws_wpm_var.trace_add("write", lambda *_a: self._update_workspace())
        wpm = self._input_box(row, self.ws_wpm_var, "wpm")
        wpm.configure(width=4)
        wpm.box.grid(row=0, column=0, sticky="w")
        wpm.grid_configure(ipady=self._px(5))

        stats = tk.Frame(row, bg=BG)
        stats.grid(row=0, column=1, sticky="e")
        self._make_draggable(stats)
        self.ws_words = tk.StringVar(value="0")
        self.ws_time = tk.StringVar(value="0:00")
        for col, (var, unit) in enumerate([(self.ws_words, "words"), (self.ws_time, "")]):
            value = tk.Label(stats, textvariable=var, bg=BG, fg=ACCENT if col else TEXT,
                             font=self.f_stat)
            value.grid(row=0, column=col * 2, sticky="e")
            self._make_draggable(value)
            if unit:
                lbl = tk.Label(stats, text=unit, bg=BG, fg=MUTED, font=self.f_label)
                lbl.grid(row=0, column=col * 2 + 1, sticky="sw",
                         padx=(self._px(4), self._px(18)), pady=(0, self._px(2)))
                self._make_draggable(lbl)

        self.calc_view.tkraise()
        self._style_tabs()
        self._build_resize_handles()

    # --------------------------------------------------------------- resizing
    def _build_resize_handles(self) -> None:
        """Right edge, bottom edge and corner grips; only shown in the Workspace."""
        win = sys.platform == "win32"
        cursors = {"e": "sb_h_double_arrow", "s": "sb_v_double_arrow",
                   "se": "size_nw_se" if win else "bottom_right_corner"}
        g = self._px(GRIP)
        self._handles = []

        def make(edge, **place):
            # BG-coloured strip with the 1px window outline drawn on its outer side
            strip = tk.Frame(self.root, bg=BG, cursor=cursors[edge])
            if edge == "e":
                tk.Frame(strip, bg=OUTLINE, width=1).pack(side="right", fill="y")
            elif edge == "s":
                tk.Frame(strip, bg=OUTLINE, height=1).pack(side="bottom", fill="x")
            strip.bind("<ButtonPress-1>", self._start_resize)
            strip.bind("<B1-Motion>", lambda e, d=edge: self._on_resize(e, d))
            self._handles.append((strip, place))
            return strip

        make("e", relx=1, y=0, anchor="ne", width=g, relheight=1)
        make("s", x=0, rely=1, anchor="sw", relwidth=1, height=g)

        # Corner grip: three small diagonal dot rows, like most desktop apps
        size = self._px(16)
        corner = tk.Canvas(self.root, width=size, height=size, bg=BG, bd=0,
                           highlightthickness=0, cursor=cursors["se"])
        dot = max(2, self._px(2))
        for i in range(3):
            for j in range(i + 1):
                x = size - self._px(4) - (i - j) * self._px(4)
                y = size - self._px(4) - j * self._px(4)
                corner.create_rectangle(x - dot, y - dot, x, y, fill=FAINT, width=0)
        corner.create_line(size - 1, 0, size - 1, size, fill=OUTLINE)
        corner.create_line(0, size - 1, size, size - 1, fill=OUTLINE)
        corner.bind("<ButtonPress-1>", self._start_resize)
        corner.bind("<B1-Motion>", lambda e: self._on_resize(e, "se"))
        self._handles.append((corner, dict(relx=1, rely=1, anchor="se")))

    def _show_resize_handles(self, show: bool) -> None:
        for widget, place in self._handles:
            if show:
                widget.place(**place)
                # Canvas.lift() raises drawn items, so raise the widget via Tk directly
                widget.tk.call("raise", widget._w)
            else:
                widget.place_forget()

    def _start_resize(self, event) -> None:
        self._resize_start = (event.x_root, event.y_root,
                              self.root.winfo_width(), self.root.winfo_height())

    def _on_resize(self, event, edge: str) -> None:
        x0, y0, w0, h0 = self._resize_start
        w = w0 + (event.x_root - x0) if "e" in edge else w0
        h = h0 + (event.y_root - y0) if "s" in edge else h0
        w = min(max(w, self._px(WORKSPACE_MIN[0])), self.root.winfo_screenwidth())
        h = min(max(h, self._px(WORKSPACE_MIN[1])), self.root.winfo_screenheight())
        self.root.geometry(f"{w}x{h}")

    def _on_script_change(self, _event=None) -> None:
        self.script.edit_modified(False)  # re-arm the <<Modified>> event
        self._update_workspace()

    def _update_workspace(self) -> None:
        """Recount words and recompute the read time."""
        text = self.script.get("1.0", "end-1c")
        if text:
            self.placeholder.place_forget()
        else:
            self.placeholder.place(x=self._px(16), y=self._px(12))
        words = count_words(text)
        self.ws_words.set(f"{words:,}")
        try:
            wpm = parse_float(self.ws_wpm_var.get())
            if wpm <= 0:
                raise ValueError
            mins, secs = split_seconds(words / wpm * 60)
            self.ws_time.set(f"{mins}:{secs:02d}")
        except ValueError:
            self.ws_time.set("\u2013:\u2013\u2013")

    def show_view(self, view: str) -> None:
        """Switch between the calculator and the workspace."""
        if view == self.view:
            return
        if view == "work":
            self.view = view
            self.work_view.tkraise()
            if self._ws_size:  # restore the size the Workspace had last time
                self.root.geometry("%dx%d" % self._ws_size)
            self._show_resize_handles(True)
            self.script.focus_set()
        else:
            # remember the Workspace size, then snap back to the fixed calculator size
            self._ws_size = (self.root.winfo_width(), self.root.winfo_height())
            self.view = view
            self._show_resize_handles(False)
            self.calc_view.tkraise()
            self._fit_height()
            self._on_mode_change()  # restores focus to the first input
        self._style_tabs()

    def _style_tabs(self) -> None:
        for view, tab in self._tabs.items():
            tab.configure(fg=TEXT if view == self.view else FAINT)

    # ------------------------------------------------------------- builders
    def _label(self, parent, text) -> tk.Label:
        lbl = tk.Label(parent, text=text, bg=BG, fg=MUTED, font=self.f_label)
        self._make_draggable(lbl)
        return lbl

    def _field_header(self, parent, row, label, hint_var) -> None:
        """Label on the left and an optional live hint on the right."""
        header = tk.Frame(parent, bg=BG)
        header.grid(row=row, column=0, sticky="ew", pady=(0, self._px(5)))
        header.columnconfigure(0, weight=1)
        self._make_draggable(header)
        self._label(header, label).grid(row=0, column=0, sticky="w")
        if hint_var is not None:
            hint = tk.Label(header, textvariable=hint_var, bg=BG, fg=ACCENT, font=self.f_hint)
            hint.grid(row=0, column=1, sticky="e")
            self._make_draggable(hint)

    def _input_box(self, parent, var, suffix=None) -> tk.Entry:
        """A bordered input with inner padding and an optional unit suffix."""
        box = tk.Frame(parent, bg=SURFACE, highlightthickness=1,
                       highlightbackground=BORDER, highlightcolor=BORDER)
        box.columnconfigure(0, weight=1)
        entry = tk.Entry(box, textvariable=var, font=self.f_entry, relief="flat", bd=0,
                         bg=SURFACE, fg=TEXT, insertbackground=TEXT, width=4,
                         readonlybackground=ACCENT_SOFT, highlightthickness=0)
        entry.grid(row=0, column=0, sticky="ew", padx=(self._px(12), 0), ipady=self._px(9))
        entry.box = box  # handles so the border / suffix can be restyled
        entry.suffix = None
        if suffix:
            entry.suffix = tk.Label(box, text=suffix, bg=SURFACE, fg=FAINT, font=self.f_label)
            entry.suffix.grid(row=0, column=1, padx=(self._px(4), self._px(12)))
            entry.suffix.bind("<Button-1>", lambda _e: entry.focus_set())
        else:
            entry.grid_configure(padx=self._px(12))

        # Accent border while focused
        entry.bind("<FocusIn>", lambda _e: self._style_box(entry, focused=True))
        entry.bind("<FocusOut>", lambda _e: self._style_box(entry, focused=False), add="+")
        box.bind("<Button-1>", lambda _e: entry.focus_set())
        return entry

    def _field(self, parent, row, label, var, hint_var, bottom_gap=18) -> tk.Entry:
        """Build one labelled input. Returns the Entry widget."""
        self._field_header(parent, row, label, hint_var)
        entry = self._input_box(parent, var)
        entry.box.grid(row=row + 1, column=0, sticky="ew", pady=(0, self._px(bottom_gap)))
        return entry

    def _duration_field(self, parent, row) -> tuple:
        """Duration as two side-by-side boxes: minutes and seconds."""
        self._field_header(parent, row, "Duration", self.duration_hint)
        pair = tk.Frame(parent, bg=BG)
        pair.grid(row=row + 1, column=0, sticky="ew", pady=(0, self._px(18)))
        pair.columnconfigure(0, weight=1, uniform="dur")
        pair.columnconfigure(1, weight=1, uniform="dur")
        minutes = self._input_box(pair, self.dur_min_var, "min")
        seconds = self._input_box(pair, self.dur_sec_var, "sec")
        minutes.box.grid(row=0, column=0, sticky="ew", padx=(0, self._px(6)))
        seconds.box.grid(row=0, column=1, sticky="ew", padx=(self._px(6), 0))
        # Roll 60+ seconds (or decimal minutes) into a tidy "M min S sec" on leave
        for entry in (minutes, seconds):
            entry.bind("<FocusOut>", lambda _e: self._normalize_duration(), add="+")
        return minutes, seconds

    def _window_button(self, parent, col, symbol, hover_bg, hover_fg, command) -> None:
        """A flat title-bar button (minimise / close) with a hover state."""
        btn = tk.Label(parent, text=symbol, bg=BG, fg=FAINT, font=self.f_ctrl,
                       width=4, pady=self._px(6), cursor="hand2")
        btn.grid(row=0, column=col, sticky="ne")
        btn.bind("<Enter>", lambda _e: btn.configure(bg=hover_bg, fg=hover_fg))
        btn.bind("<Leave>", lambda _e: btn.configure(bg=BG, fg=FAINT))
        btn.bind("<ButtonRelease-1>", lambda _e: command())

    # -------------------------------------------------------------- updates
    def _in_background(self, work, on_done) -> None:
        """Run `work()` on a thread; call `on_done(result, error)` on the UI thread."""
        box = {}

        def runner():
            try:
                box["result"] = work()
            except Exception as exc:  # network down, API limit, etc.
                box["error"] = exc

        thread = threading.Thread(target=runner, daemon=True)
        thread.start()

        def poll():
            if thread.is_alive():
                self.root.after(100, poll)
            else:
                on_done(box.get("result"), box.get("error"))
        poll()

    def _footer_status(self, text: str, reset_after_ms: int = 0) -> None:
        self.update_link.configure(text=text)
        if reset_after_ms:
            self.root.after(reset_after_ms,
                            lambda: self.update_link.configure(text="Check for updates"))

    def check_for_updates(self, manual: bool) -> None:
        """Ask GitHub for a newer release. Silent on failure unless manual."""
        if self._updating:
            return
        if manual:
            self._footer_status("Checking\u2026")

        def done(result, error):
            if error is not None:
                if manual:
                    self._footer_status("Couldn't check for updates", 4000)
                return
            if result is None:
                if manual:
                    self._footer_status("You're up to date", 4000)
                return
            if manual:
                self._footer_status("Check for updates")
            self._update_info = result
            self._show_banner(f"Version {result[0]} is available", "Update now")

        self._in_background(lambda: updater.check_latest(__version__), done)

    def _show_banner(self, text: str, action: str = "") -> None:
        self.banner_text.set(text)
        self.banner_action.configure(text=action)
        if not self.banner.winfo_ismapped():
            self.banner.grid()
            self._fit_height()

    def install_update(self) -> None:
        """Download the new .exe, swap it in, and restart."""
        if self._updating or not self._update_info:
            return
        version, url = self._update_info
        # Running from source, or release has no .exe: open the release page
        if not updater.is_frozen() or not url:
            webbrowser.open(updater.RELEASES_PAGE)
            return

        self._updating = True
        self._show_banner("Downloading update\u2026 0%")

        def progress(fraction):
            # Called from the worker thread: hand the update to the UI thread
            self.root.after(0, lambda: self.banner_text.set(
                f"Downloading update\u2026 {int(fraction * 100)}%"))

        def done(path, error):
            if error is not None:
                self._updating = False
                self._show_banner("Update failed. Try again later.", "Retry")
                return
            self._show_banner(f"Installing v{version}\u2026")
            try:
                updater.apply_and_restart(path)
            except Exception:
                self._updating = False
                self._show_banner("Update failed. Try again later.", "Retry")
                return
            self.root.after(300, self.root.destroy)

        self._in_background(lambda: updater.download(url, progress), done)

    # ------------------------------------------------- borderless window glue
    def _make_draggable(self, widget) -> None:
        """Let the user move the window by dragging this widget."""
        widget.bind("<ButtonPress-1>", self._start_drag, add="+")
        widget.bind("<B1-Motion>", self._on_drag, add="+")

    def _start_drag(self, event) -> None:
        self._drag_offset = (event.x_root - self.root.winfo_x(),
                             event.y_root - self.root.winfo_y())

    def _on_drag(self, event) -> None:
        dx, dy = self._drag_offset
        self.root.geometry(f"+{event.x_root - dx}+{event.y_root - dy}")

    def _show_in_taskbar(self) -> None:
        """Give the borderless window a taskbar button on Windows."""
        if sys.platform == "win32":
            try:
                import ctypes
                GWL_EXSTYLE, WS_EX_APPWINDOW, WS_EX_TOOLWINDOW = -20, 0x00040000, 0x00000080
                user32 = ctypes.windll.user32
                hwnd = user32.GetParent(self.root.winfo_id())
                style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                style = (style & ~WS_EX_TOOLWINDOW) | WS_EX_APPWINDOW
                user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
                self.root.withdraw()
                self.root.after(10, self.root.deiconify)
            except Exception:
                pass
        self.root.after(30, self.root.focus_force)

    def _minimize(self) -> None:
        """Borderless windows can't be iconified directly, so toggle the frame."""
        self.root.overrideredirect(False)
        self.root.iconify()
        self.root.bind("<Map>", self._on_restore)

    def _on_restore(self, _event) -> None:
        if self.root.state() == "normal":
            self.root.unbind("<Map>")
            self.root.overrideredirect(True)
            self.root.after(10, self._show_in_taskbar)

    # -------------------------------------------------------------- callbacks
    def _style_box(self, entry, focused: bool) -> None:
        """Border colour for an input: accent when focused, soft when result."""
        if str(entry.cget("state")) == "readonly":
            color = ACCENT_SOFT
        else:
            color = ACCENT if focused else BORDER
        entry.box.configure(highlightbackground=color, highlightcolor=color)

    def _select_mode(self, value: str) -> None:
        self.mode.set(value)
        self._on_mode_change()

    def _on_mode_change(self) -> None:
        """Lock + highlight the result field; unlock the other two inputs."""
        current = self.mode.get()

        for value, seg in self._segments.items():
            if value == current:
                seg.configure(bg=SURFACE, fg=TEXT, font=self.f_seg_on)
            else:
                seg.configure(bg=SEG_BG, fg=MUTED, font=self.f_seg)

        first_input = None
        for mode, entries in self._output_entry.items():
            for entry in entries:
                is_result = mode == current
                entry.configure(state="readonly" if is_result else "normal",
                                fg=ACCENT if is_result else TEXT)
                bg = ACCENT_SOFT if is_result else SURFACE
                entry.box.configure(bg=bg)
                if entry.suffix is not None:
                    entry.suffix.configure(bg=bg)
                if not is_result:
                    first_input = first_input or entry
                self._style_box(entry, focused=False)

        self.error_text.set("")
        if first_input is not None:
            first_input.focus_set()

    def _update_duration_hint(self, *_args) -> None:
        """Show the duration in decimal minutes while the user types."""
        try:
            total = parse_duration(self.dur_min_var.get(), self.dur_sec_var.get())
            self.duration_hint.set(f"{total / 60:.2f} min" if total > 0 else "")
        except ValueError:
            self.duration_hint.set("")

    def _normalize_duration(self) -> None:
        """Rewrite e.g. 1 min 90 sec as 2 min 30 sec (and 2.5 min as 2 min 30 sec)."""
        if self.mode.get() == MODE_DURATION:
            return  # duration is the read-only result in this mode
        try:
            total = parse_duration(self.dur_min_var.get(), self.dur_sec_var.get())
            seconds = float(self.dur_sec_var.get() or 0)
            minutes = float(self.dur_min_var.get() or 0)
        except ValueError:
            return  # leave invalid input alone; Calculate reports it
        if seconds >= 60 or minutes != int(minutes):
            mins, secs = split_seconds(total)
            self.dur_min_var.set(str(mins))
            self.dur_sec_var.set(str(secs))

    def _update_pace_hint(self, *_args) -> None:
        """Show the pacing profile for the current WPM value and move the gauge."""
        try:
            wpm = parse_float(self.wpm_var.get())
            self.pace_hint.set(pace_profile(wpm) if wpm > 0 else "")
        except ValueError:
            self.pace_hint.set("")
        self._draw_gauge()

    # ---------------------------------------------------------------- gauge
    def _current_wpm(self):
        try:
            wpm = parse_float(self.wpm_var.get())
            return wpm if wpm > 0 else None
        except ValueError:
            return None

    def _draw_gauge(self) -> None:
        """Draw a three-zone pace bar with a marker at the current WPM."""
        c = self.gauge
        c.delete("all")
        width = c.winfo_width()
        if width <= 1:
            return
        bar_top, bar_h = self._px(12), self._px(8)
        r = self._px(9)  # marker radius; inset so it never clips at the ends

        def x_for(wpm: float) -> float:
            t = (min(max(wpm, GAUGE_MIN), GAUGE_MAX) - GAUGE_MIN) / (GAUGE_MAX - GAUGE_MIN)
            return r + t * (width - 2 * r)

        wpm = self._current_wpm()
        for start, end, color, caption in GAUGE_ZONES:
            x0, x1 = x_for(start), x_for(end)
            c.create_rectangle(x0, bar_top, x1, bar_top + bar_h, fill=color, width=0)
            active = wpm is not None and start <= min(max(wpm, GAUGE_MIN), GAUGE_MAX) <= end
            c.create_text((x0 + x1) / 2, bar_top + bar_h + self._px(14), text=caption,
                          fill=ACCENT if active else FAINT, font=self.f_gauge)

        # Tick values at the zone boundaries
        for boundary in (130, 160):
            c.create_text(x_for(boundary), bar_top - self._px(7), text=str(boundary),
                          fill=FAINT, font=self.f_gauge)

        if wpm is not None:
            x, cy = x_for(wpm), bar_top + bar_h / 2
            c.create_oval(x - r, cy - r, x + r, cy + r, fill=SURFACE, outline=ACCENT,
                          width=self._px(3))

    # ------------------------------------------------------------ calculation
    def calculate(self) -> None:
        """Read the two inputs, solve for the third, and display it."""
        if self.view != "calc":
            return
        self.error_text.set("")
        self._normalize_duration()
        mode = self.mode.get()

        try:
            if mode == MODE_WPM:
                words = parse_int(self.words_var.get())
                seconds = parse_duration(self.dur_min_var.get(), self.dur_sec_var.get())
                if seconds <= 0 or words < 0:
                    self._show_error(ERROR_ZERO, mode)
                    return
                self.wpm_var.set(str(round(words / (seconds / 60))))

            elif mode == MODE_WORDS:
                seconds = parse_duration(self.dur_min_var.get(), self.dur_sec_var.get())
                wpm = parse_int(self.wpm_var.get())
                if seconds <= 0 or wpm <= 0:
                    self._show_error(ERROR_ZERO, mode)
                    return
                self.words_var.set(str(round(seconds / 60 * wpm)))

            else:  # MODE_DURATION
                words = parse_int(self.words_var.get())
                wpm = parse_int(self.wpm_var.get())
                if wpm <= 0 or words < 0:
                    self._show_error(ERROR_ZERO, mode)
                    return
                mins, secs = split_seconds(words / wpm * 60)
                self.dur_min_var.set(str(mins))
                self.dur_sec_var.set(str(secs))

        except ValueError:
            # Empty strings, letters, or decimals in whole-number fields
            self._show_error(ERROR_INVALID, mode)

    def _output_vars(self, mode: str) -> list:
        """The StringVar(s) of the result field for a given mode."""
        return {MODE_WPM: [self.wpm_var],
                MODE_WORDS: [self.words_var],
                MODE_DURATION: [self.dur_min_var, self.dur_sec_var]}[mode]

    def _show_error(self, message: str, mode: str) -> None:
        """Display an inline error and clear the stale result."""
        self.error_text.set(message)
        for var in self._output_vars(mode):
            var.set("")


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def main() -> None:
    enable_windows_dpi_awareness()
    root = tk.Tk()
    PacingCalculatorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
