#!/usr/bin/env python3
"""
Chrome Text Finder
------------------
Enter text in the GUI and it will be found in the active Chrome tab.
The mouse pointer will move to the center of the found text.

Requirements:
    pip install pychrome pyautogui

Chrome must be started with remote debugging enabled:
    chrome --remote-debugging-port=9222
    google-chrome --remote-debugging-port=9222  (Linux)
"""

import sys
import json
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

import pychrome       # noqa: E402
import pyautogui      # noqa: E402

# Prevent pyautogui from throwing on move to (0,0) safety corner
pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0


# ---------------------------------------------------------------------------
# JavaScript injected into the Chrome tab to locate every occurrence of a
# string and return screen-level coordinates for each one.
# ---------------------------------------------------------------------------
_FIND_TEXT_JS = """
(function(searchText, caseSensitive) {
    var needle   = caseSensitive ? searchText : searchText.toLowerCase();
    var results  = [];
    var chromeY  = window.outerHeight - window.innerHeight;  // tabs + address bar height

    var walker = document.createTreeWalker(
        document.body,
        NodeFilter.SHOW_TEXT,
        null,
        false
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


class TextFinderApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Chrome Text Finder")
        self.root.resizable(False, False)

        self._browser = None
        self._results: list[dict] = []
        self._index: int = -1

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
                  font=("Arial", 15, "bold")).grid(row=0, column=0, columnspan=3, pady=(0, 10))

        # ---- search row ----
        ttk.Label(outer, text="Find text:").grid(row=1, column=0, sticky="w", **pad)

        self._search_var = tk.StringVar()
        entry = ttk.Entry(outer, textvariable=self._search_var, width=38, font=("Arial", 11))
        entry.grid(row=1, column=1, columnspan=2, sticky="ew", **pad)
        entry.bind("<Return>", lambda _e: self._search())
        entry.focus_set()

        # ---- options ----
        self._case_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(outer, text="Case sensitive",
                        variable=self._case_var).grid(row=2, column=1, sticky="w", padx=8)

        # ---- buttons ----
        btn_row = ttk.Frame(outer)
        btn_row.grid(row=3, column=0, columnspan=3, pady=8)

        self._find_btn = ttk.Button(btn_row, text="Find", width=12, command=self._search)
        self._find_btn.pack(side="left", padx=4)

        self._prev_btn = ttk.Button(btn_row, text="◀  Prev", width=10,
                                    command=self._prev, state="disabled")
        self._prev_btn.pack(side="left", padx=4)

        self._next_btn = ttk.Button(btn_row, text="Next  ▶", width=10,
                                    command=self._next, state="disabled")
        self._next_btn.pack(side="left", padx=4)

        # ---- counter ----
        self._counter_var = tk.StringVar()
        ttk.Label(outer, textvariable=self._counter_var,
                  font=("Arial", 9)).grid(row=4, column=0, columnspan=3, pady=2)

        # ---- status bar ----
        self._status_var = tk.StringVar(value="Connecting to Chrome…")
        ttk.Label(outer, textvariable=self._status_var,
                  foreground="gray", font=("Arial", 9),
                  wraplength=380, justify="left").grid(
            row=5, column=0, columnspan=3, pady=(4, 0))

        # ---- instructions ----
        box = ttk.LabelFrame(outer, text="How to start Chrome with debugging", padding=8)
        box.grid(row=6, column=0, columnspan=3, pady=(12, 0), sticky="ew")

        hint = (
            "Windows / Linux:\n"
            "  chrome --remote-debugging-port=9222\n\n"
            "macOS:\n"
            "  /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome \\\n"
            "      --remote-debugging-port=9222"
        )
        ttk.Label(box, text=hint, font=("Courier", 8), justify="left").pack(anchor="w")

    # ------------------------------------------------------------------
    # Chrome connection
    # ------------------------------------------------------------------

    def _connect(self):
        try:
            self._browser = pychrome.Browser(url="http://127.0.0.1:9222")
            tabs = self._browser.list_tab()
            pages = [t for t in tabs if getattr(t, "type", "") == "page"]
            n = len(pages) or len(tabs)
            self._status_var.set(f"Connected to Chrome  ({n} tab(s) found).")
        except Exception:
            self._browser = None
            self._status_var.set(
                "Could not connect to Chrome. "
                "Start it with --remote-debugging-port=9222  (see instructions below)."
            )

    def _active_tab(self):
        tabs = self._browser.list_tab()
        pages = [t for t in tabs if getattr(t, "type", "") == "page"]
        return pages[0] if pages else (tabs[0] if tabs else None)

    # ------------------------------------------------------------------
    # Search logic
    # ------------------------------------------------------------------

    def _search(self):
        text = self._search_var.get().strip()
        if not text:
            messagebox.showwarning("Empty search", "Please enter the text you want to find.")
            return

        if not self._browser:
            self._connect()
            if not self._browser:
                messagebox.showerror(
                    "Chrome not connected",
                    "Cannot reach Chrome on port 9222.\n"
                    "Start Chrome with:\n  chrome --remote-debugging-port=9222",
                )
                return

        self._status_var.set("Searching…")
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
            self._status_var.set(f"Error: {exc}")
            return

        if data and data.get("count", 0) > 0:
            self._results = data["results"]
            self._index = 0
            total = data["count"]
            self._counter_var.set(f"1 of {total}")
            self._prev_btn.config(state="normal" if total > 1 else "disabled")
            self._next_btn.config(state="normal" if total > 1 else "disabled")
            self._status_var.set(f'Found {total} occurrence(s) of "{text}".')
            self._move_to(0)
        else:
            self._results = []
            self._index = -1
            self._counter_var.set("")
            self._prev_btn.config(state="disabled")
            self._next_btn.config(state="disabled")
            self._status_var.set(f'"{text}" was not found on the page.')

    @staticmethod
    def _run_js(tab, search_text: str, case_sensitive: bool) -> dict:
        """Execute the finder JS inside the tab and return the result dict."""
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
            total = len(self._results)
            self._status_var.set(
                f"Mouse at result {index + 1} of {total}  →  screen ({x}, {y})"
            )
        except pyautogui.FailSafeException:
            self._status_var.set("pyautogui failsafe triggered (mouse was at corner).")
        except Exception as exc:
            self._status_var.set(f"Mouse move error: {exc}")

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
