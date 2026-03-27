#!/usr/bin/env python3
"""
Chrome Text Finder
------------------
Enter text in the GUI and it will be found in the active Chrome tab.
The mouse pointer will move to the center of the found text.

Requirements:
    pip install pychrome pyautogui

Chrome must be started with remote debugging enabled, OR use the
"Launch Chrome" button in the app to do it automatically.
"""

import os
import sys
import json
import time
import platform
import subprocess
import tkinter as tk
from tkinter import ttk, messagebox


def _ensure_packages():
    missing = []
    try:
        import pychrome  # noqa: F401
    except ImportError:
        missing.append("pychrome")
    try:
        import pyautogui  # noqa: F401
    except ImportError:
        missing.append("pyautogui")
    if missing:
        print(f"Installing missing packages: {', '.join(missing)}")
        subprocess.check_call([sys.executable, "-m", "pip", "install"] + missing)


_ensure_packages()

import pychrome   # noqa: E402
import pyautogui  # noqa: E402

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0

# ---------------------------------------------------------------------------
# Chrome executable candidates per platform
# ---------------------------------------------------------------------------
DEFAULT_PORT = 9222

_CHROME_CANDIDATES = {
    "Windows": [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ],
    "Darwin": [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
    ],
    "Linux": [
        "google-chrome",
        "google-chrome-stable",
        "chromium-browser",
        "chromium",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium-browser",
    ],
}

# ---------------------------------------------------------------------------
# JavaScript injected into the Chrome tab to locate every occurrence of a
# string and return screen-level coordinates for each one.
# ---------------------------------------------------------------------------
_FIND_TEXT_JS = """
(function(searchText, caseSensitive) {
    var needle  = caseSensitive ? searchText : searchText.toLowerCase();
    var results = [];
    var chromeY = window.outerHeight - window.innerHeight;  // tabs + address bar

    var walker = document.createTreeWalker(
        document.body, NodeFilter.SHOW_TEXT, null, false
    );

    var node;
    while ((node = walker.nextNode())) {
        var hay = caseSensitive ? node.textContent : node.textContent.toLowerCase();
        var pos = 0;
        while (true) {
            pos = hay.indexOf(needle, pos);
            if (pos === -1) break;
            try {
                var range = document.createRange();
                range.setStart(node, pos);
                range.setEnd(node, pos + searchText.length);
                var r = range.getBoundingClientRect();
                if (r.width > 0 && r.height > 0) {
                    results.push({
                        screenX: window.screenX + r.left + r.width  / 2,
                        screenY: window.screenY + chromeY + r.top  + r.height / 2
                    });
                }
            } catch (e) {}
            pos += searchText.length;
        }
    }

    return { count: results.length, results: results };
})(SEARCH_TEXT_PLACEHOLDER, CASE_SENSITIVE_PLACEHOLDER)
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_chrome_executable() -> str | None:
    """Return the path to a Chrome/Chromium executable, or None."""
    system = platform.system()
    candidates = _CHROME_CANDIDATES.get(system, _CHROME_CANDIDATES["Linux"])
    for c in candidates:
        # For absolute paths check existence; for bare names check PATH
        if os.path.isabs(c):
            if os.path.isfile(c):
                return c
        else:
            result = subprocess.run(
                ["which", c], capture_output=True, text=True
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
    return None


def _launch_chrome(exe: str, port: int) -> subprocess.Popen:
    """Start Chrome with remote debugging on the given port."""
    args = [
        exe,
        f"--remote-debugging-port={port}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    # On Linux detach from the terminal
    kwargs = {}
    if platform.system() == "Linux":
        kwargs["start_new_session"] = True
    elif platform.system() == "Windows":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    return subprocess.Popen(args, **kwargs)


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

class TextFinderApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Chrome Text Finder")
        self.root.resizable(False, False)

        self._browser = None
        self._results: list[dict] = []
        self._index: int = -1
        self._chrome_proc: subprocess.Popen | None = None

        self._build_ui()
        self._connect()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        pad = {"padx": 8, "pady": 4}
        outer = ttk.Frame(self.root, padding=14)
        outer.grid(row=0, column=0, sticky="nsew")

        ttk.Label(outer, text="Chrome Text Finder",
                  font=("Arial", 15, "bold")).grid(
            row=0, column=0, columnspan=3, pady=(0, 10))

        # port input
        ttk.Label(outer, text="Debug port:").grid(row=1, column=0, sticky="w", **pad)
        self._port_var = tk.StringVar(value=str(DEFAULT_PORT))
        port_entry = ttk.Entry(outer, textvariable=self._port_var, width=7)
        port_entry.grid(row=1, column=1, sticky="w", **pad)

        # search input
        ttk.Label(outer, text="Find text:").grid(row=2, column=0, sticky="w", **pad)
        self._search_var = tk.StringVar()
        entry = ttk.Entry(outer, textvariable=self._search_var, width=38, font=("Arial", 11))
        entry.grid(row=2, column=1, columnspan=2, sticky="ew", **pad)
        entry.bind("<Return>", lambda _e: self._search())
        entry.focus_set()

        # case-sensitive toggle
        self._case_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(outer, text="Case sensitive",
                        variable=self._case_var).grid(row=3, column=1, sticky="w", padx=8)

        # navigation buttons
        btn_row = ttk.Frame(outer)
        btn_row.grid(row=4, column=0, columnspan=3, pady=8)

        self._find_btn = ttk.Button(btn_row, text="Find", width=12, command=self._search)
        self._find_btn.pack(side="left", padx=4)

        self._prev_btn = ttk.Button(btn_row, text="◀  Prev", width=10,
                                    command=self._prev, state="disabled")
        self._prev_btn.pack(side="left", padx=4)

        self._next_btn = ttk.Button(btn_row, text="Next  ▶", width=10,
                                    command=self._next, state="disabled")
        self._next_btn.pack(side="left", padx=4)

        # match counter
        self._counter_var = tk.StringVar()
        ttk.Label(outer, textvariable=self._counter_var,
                  font=("Arial", 9)).grid(row=5, column=0, columnspan=3, pady=2)

        # status bar
        self._status_var = tk.StringVar(value="Connecting to Chrome…")
        self._status_lbl = ttk.Label(outer, textvariable=self._status_var,
                                     foreground="gray", font=("Arial", 9),
                                     wraplength=400, justify="left")
        self._status_lbl.grid(row=6, column=0, columnspan=3, pady=(4, 0))

        # Chrome connection panel
        conn_box = ttk.LabelFrame(outer, text="Chrome connection", padding=8)
        conn_box.grid(row=7, column=0, columnspan=3, pady=(12, 0), sticky="ew")

        self._launch_btn = ttk.Button(conn_box, text="Launch Chrome with debugging",
                                      command=self._launch_chrome_clicked)
        self._launch_btn.pack(side="left", padx=(0, 8))

        self._reconnect_btn = ttk.Button(conn_box, text="Reconnect",
                                         command=self._reconnect)
        self._reconnect_btn.pack(side="left")

        # manual-launch hint
        hint_box = ttk.LabelFrame(outer, text="Manual launch commands", padding=8)
        hint_box.grid(row=8, column=0, columnspan=3, pady=(8, 0), sticky="ew")
        hint = (
            "Windows / Linux:\n"
            "  chrome --remote-debugging-port=9222\n\n"
            "macOS:\n"
            '  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \\\n'
            "      --remote-debugging-port=9222"
        )
        ttk.Label(hint_box, text=hint, font=("Courier", 8),
                  justify="left").pack(anchor="w")

    # ------------------------------------------------------------------
    # Chrome connection
    # ------------------------------------------------------------------

    def _set_status(self, msg: str, color: str = "gray"):
        self._status_var.set(msg)
        self._status_lbl.config(foreground=color)

    def _port(self) -> int:
        try:
            p = int(self._port_var.get().strip())
            if 1 <= p <= 65535:
                return p
        except ValueError:
            pass
        self._port_var.set(str(DEFAULT_PORT))
        return DEFAULT_PORT

    def _connect(self) -> bool:
        """Try to connect to Chrome on the configured port. Returns True on success."""
        port = self._port()
        try:
            browser = pychrome.Browser(url=f"http://127.0.0.1:{port}")
            tabs = browser.list_tab()          # raises if Chrome isn't there
            pages = [t for t in tabs if getattr(t, "type", "") == "page"]
            n = len(pages) or len(tabs)
            self._browser = browser
            self._set_status(f"Connected to Chrome  ({n} tab(s) found).", "green")
            return True
        except Exception:
            self._browser = None
            self._set_status(
                f"Not connected on port {port}. Use 'Launch Chrome with debugging' or 'Reconnect'.",
                "red",
            )
            return False

    def _reconnect(self):
        self._set_status("Connecting…")
        self.root.update_idletasks()
        self._connect()

    def _launch_chrome_clicked(self):
        exe = _find_chrome_executable()
        if not exe:
            messagebox.showerror(
                "Chrome not found",
                "Could not find Google Chrome on this machine.\n\n"
                "Please install Chrome or launch it manually with:\n"
                "  chrome --remote-debugging-port=9222",
            )
            return

        self._set_status(f"Launching Chrome: {exe}")
        self.root.update_idletasks()

        try:
            self._chrome_proc = _launch_chrome(exe, self._port())
        except Exception as exc:
            messagebox.showerror("Launch failed", str(exc))
            return

        # Poll until Chrome accepts connections (up to 10 s)
        self._set_status("Waiting for Chrome to start…")
        self.root.update_idletasks()
        self._poll_connect(attempts=20, delay_ms=500)

    def _poll_connect(self, attempts: int, delay_ms: int):
        """Retry _connect() up to `attempts` times, waiting delay_ms between tries."""
        if self._connect():
            return
        if attempts > 1:
            self.root.after(delay_ms, lambda: self._poll_connect(attempts - 1, delay_ms))
        else:
            self._set_status(
                "Chrome started but could not connect on port 9222. "
                "Try clicking Reconnect in a moment.",
                "red",
            )

    def _active_tab(self):
        tabs = self._browser.list_tab()
        pages = [t for t in tabs if getattr(t, "type", "") == "page"]
        return pages[0] if pages else (tabs[0] if tabs else None)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def _search(self):
        text = self._search_var.get().strip()
        if not text:
            messagebox.showwarning("Empty search", "Please enter text to search for.")
            return

        if not self._browser:
            if not self._connect():
                messagebox.showerror(
                    "Chrome not connected",
                    "Cannot reach Chrome on port 9222.\n\n"
                    "Click 'Launch Chrome with debugging' to start it automatically,\n"
                    "or start Chrome manually with:\n"
                    "  chrome --remote-debugging-port=9222",
                )
                return

        self._set_status("Searching…")
        self.root.update_idletasks()

        tab = self._active_tab()
        if not tab:
            messagebox.showerror("No tab", "No Chrome tab is available.")
            return

        try:
            tab.start()
            data = self._run_js(tab, text, self._case_var.get())
            tab.stop()
        except Exception as exc:
            try:
                tab.stop()
            except Exception:
                pass
            messagebox.showerror("Error", f"Failed to communicate with Chrome:\n{exc}")
            self._set_status(f"Error: {exc}", "red")
            return

        if data and data.get("count", 0) > 0:
            self._results = data["results"]
            self._index = 0
            total = data["count"]
            self._counter_var.set(f"1 of {total}")
            nav_state = "normal" if total > 1 else "disabled"
            self._prev_btn.config(state=nav_state)
            self._next_btn.config(state=nav_state)
            self._set_status(f'Found {total} occurrence(s) of "{text}".', "green")
            self._move_to(0)
        else:
            self._results = []
            self._index = -1
            self._counter_var.set("")
            self._prev_btn.config(state="disabled")
            self._next_btn.config(state="disabled")
            self._set_status(f'"{text}" was not found on the page.', "gray")

    @staticmethod
    def _run_js(tab, search_text: str, case_sensitive: bool) -> dict:
        js = _FIND_TEXT_JS.replace(
            "SEARCH_TEXT_PLACEHOLDER", json.dumps(search_text)
        ).replace(
            "CASE_SENSITIVE_PLACEHOLDER", "true" if case_sensitive else "false"
        )
        outcome = tab.Runtime.evaluate(expression=js, returnByValue=True)
        if outcome and "result" in outcome and "value" in outcome["result"]:
            return outcome["result"]["value"]
        return {}

    # ------------------------------------------------------------------
    # Navigation & mouse
    # ------------------------------------------------------------------

    def _move_to(self, index: int):
        if not self._results or not (0 <= index < len(self._results)):
            return
        r = self._results[index]
        x, y = int(r["screenX"]), int(r["screenY"])
        try:
            pyautogui.moveTo(x, y, duration=0.25)
            self._set_status(
                f"Mouse at result {index + 1} of {len(self._results)}  →  screen ({x}, {y})",
                "green",
            )
        except pyautogui.FailSafeException:
            self._set_status("pyautogui failsafe triggered (mouse was at a screen corner).", "red")
        except Exception as exc:
            self._set_status(f"Mouse move error: {exc}", "red")

    def _next(self):
        if not self._results:
            return
        self._index = (self._index + 1) % len(self._results)
        self._counter_var.set(f"{self._index + 1} of {len(self._results)}")
        self._move_to(self._index)

    def _prev(self):
        if not self._results:
            return
        self._index = (self._index - 1) % len(self._results)
        self._counter_var.set(f"{self._index + 1} of {len(self._results)}")
        self._move_to(self._index)


# ---------------------------------------------------------------------------

def main():
    root = tk.Tk()
    TextFinderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
