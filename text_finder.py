#!/usr/bin/env python3
"""
Chrome Text Finder  –  screenshot + OCR edition
------------------------------------------------
Takes a screenshot of your screen, uses Tesseract OCR to locate the
text you typed, then moves the mouse to its centre.

No Chrome flags or remote-debugging ports required.

Python deps (auto-installed):
    pip install pytesseract Pillow pyautogui

System dep – Tesseract OCR engine:
    Linux  : sudo apt install tesseract-ocr
    macOS  : brew install tesseract
    Windows: https://github.com/UB-Mannheim/tesseract/wiki
"""

import sys
import subprocess
import platform
import tkinter as tk
from tkinter import ttk, messagebox


# ---------------------------------------------------------------------------
# Auto-install Python packages
# ---------------------------------------------------------------------------

def _ensure_packages():
    pkgs = {"pytesseract": "pytesseract", "PIL": "Pillow", "pyautogui": "pyautogui"}
    missing = []
    for mod, pkg in pkgs.items():
        try:
            __import__(mod)
        except ImportError:
            missing.append(pkg)
    if missing:
        print(f"Installing: {', '.join(missing)}")
        subprocess.check_call([sys.executable, "-m", "pip", "install"] + missing)


_ensure_packages()

import pyautogui        # noqa: E402
import pytesseract      # noqa: E402
from PIL import Image   # noqa: E402

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0


# ---------------------------------------------------------------------------
# OCR-based text finder
# ---------------------------------------------------------------------------

def _find_text_on_screen(search_text: str, case_sensitive: bool) -> list[dict]:
    """
    Capture the screen, OCR it, and return a list of
    {"screenX": int, "screenY": int} dicts for every match.
    """
    # -- screenshot --
    screenshot: Image.Image = pyautogui.screenshot()

    # -- OCR: get per-word bounding boxes --
    data = pytesseract.image_to_data(screenshot, output_type=pytesseract.Output.DICT)

    n = len(data["text"])
    needle = search_text.strip()
    if not needle:
        return []

    needle_words = needle.split() if case_sensitive else needle.lower().split()

    # Group word indices by line  (block, paragraph, line)
    lines: dict[tuple, list[int]] = {}
    for i in range(n):
        conf = int(data["conf"][i])
        if conf < 0:          # layout artefact, skip
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        lines.setdefault(key, []).append(i)

    results = []

    for indices in lines.values():
        raw_words = [data["text"][i] for i in indices]
        cmp_words = raw_words if case_sensitive else [w.lower() for w in raw_words]

        # Slide a window of len(needle_words) across the line
        wlen = len(needle_words)
        for start in range(len(cmp_words) - wlen + 1):
            if cmp_words[start : start + wlen] == needle_words:
                span = indices[start : start + wlen]
                x1 = min(data["left"][i] for i in span)
                y1 = min(data["top"][i] for i in span)
                x2 = max(data["left"][i] + data["width"][i]  for i in span)
                y2 = max(data["top"][i] + data["height"][i] for i in span)
                results.append({"screenX": (x1 + x2) // 2,
                                 "screenY": (y1 + y2) // 2})

    # Also search within single words for substring matches
    # (catches cases where OCR merges/splits words differently)
    if not results and len(needle_words) == 1:
        for indices in lines.values():
            for i in indices:
                word = data["text"][i] if case_sensitive else data["text"][i].lower()
                if needle_words[0] in word:
                    x = data["left"][i] + data["width"][i]  // 2
                    y = data["top"][i]  + data["height"][i] // 2
                    results.append({"screenX": x, "screenY": y})

    return results


def _check_tesseract() -> bool:
    """Return True if the tesseract binary is on PATH."""
    try:
        pytesseract.get_tesseract_version()
        return True
    except pytesseract.TesseractNotFoundError:
        return False


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

class TextFinderApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Chrome Text Finder")
        self.root.resizable(False, False)

        self._results: list[dict] = []
        self._index: int = -1

        self._build_ui()
        self._check_tesseract_on_start()

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

        # search input
        ttk.Label(outer, text="Find text:").grid(row=1, column=0, sticky="w", **pad)
        self._search_var = tk.StringVar()
        entry = ttk.Entry(outer, textvariable=self._search_var,
                          width=40, font=("Arial", 11))
        entry.grid(row=1, column=1, columnspan=2, sticky="ew", **pad)
        entry.bind("<Return>", lambda _e: self._search())
        entry.focus_set()

        # options
        self._case_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(outer, text="Case sensitive",
                        variable=self._case_var).grid(
            row=2, column=1, sticky="w", padx=8)

        # buttons
        btn_row = ttk.Frame(outer)
        btn_row.grid(row=3, column=0, columnspan=3, pady=8)

        self._find_btn = ttk.Button(btn_row, text="Find", width=12,
                                    command=self._search)
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
                  font=("Arial", 9)).grid(row=4, column=0, columnspan=3, pady=2)

        # status bar
        self._status_var = tk.StringVar(value="Ready.")
        self._status_lbl = ttk.Label(outer, textvariable=self._status_var,
                                     foreground="gray", font=("Arial", 9),
                                     wraplength=420, justify="left")
        self._status_lbl.grid(row=5, column=0, columnspan=3, pady=(4, 0))

        # Tesseract install hint
        box = ttk.LabelFrame(outer, text="Tesseract OCR – install if missing", padding=8)
        box.grid(row=6, column=0, columnspan=3, pady=(12, 0), sticky="ew")
        hint = (
            "Linux : sudo apt install tesseract-ocr\n"
            "macOS : brew install tesseract\n"
            "Windows: https://github.com/UB-Mannheim/tesseract/wiki"
        )
        ttk.Label(box, text=hint, font=("Courier", 8),
                  justify="left").pack(anchor="w")

    # ------------------------------------------------------------------
    # Status helper
    # ------------------------------------------------------------------

    def _set_status(self, msg: str, color: str = "gray"):
        self._status_var.set(msg)
        self._status_lbl.config(foreground=color)

    # ------------------------------------------------------------------
    # Tesseract check
    # ------------------------------------------------------------------

    def _check_tesseract_on_start(self):
        if not _check_tesseract():
            self._set_status(
                "Tesseract not found. Install it using the instructions below, then restart.",
                "red",
            )
        else:
            ver = pytesseract.get_tesseract_version()
            self._set_status(f"Ready  (Tesseract {ver}).", "green")

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def _search(self):
        text = self._search_var.get().strip()
        if not text:
            messagebox.showwarning("Empty search", "Please enter text to search for.")
            return

        if not _check_tesseract():
            messagebox.showerror(
                "Tesseract not found",
                "Tesseract OCR is not installed.\n\n"
                "Linux : sudo apt install tesseract-ocr\n"
                "macOS : brew install tesseract\n"
                "Windows: https://github.com/UB-Mannheim/tesseract/wiki",
            )
            return

        self._set_status("Taking screenshot and running OCR… (may take a few seconds)")
        self._find_btn.config(state="disabled")
        self.root.update_idletasks()

        try:
            results = _find_text_on_screen(text, self._case_var.get())
        except Exception as exc:
            self._set_status(f"Error: {exc}", "red")
            self._find_btn.config(state="normal")
            messagebox.showerror("OCR error", str(exc))
            return
        finally:
            self._find_btn.config(state="normal")

        if results:
            self._results = results
            self._index = 0
            total = len(results)
            self._counter_var.set(f"1 of {total}")
            nav = "normal" if total > 1 else "disabled"
            self._prev_btn.config(state=nav)
            self._next_btn.config(state=nav)
            self._set_status(f'Found {total} occurrence(s) of "{text}".', "green")
            self._move_to(0)
        else:
            self._results = []
            self._index = -1
            self._counter_var.set("")
            self._prev_btn.config(state="disabled")
            self._next_btn.config(state="disabled")
            self._set_status(
                f'"{text}" not found on screen. '
                "Check spelling, or try different capitalisation.",
                "gray",
            )

    # ------------------------------------------------------------------
    # Navigation & mouse
    # ------------------------------------------------------------------

    def _move_to(self, index: int):
        if not self._results or not (0 <= index < len(self._results)):
            return
        r = self._results[index]
        x, y = r["screenX"], r["screenY"]
        try:
            pyautogui.moveTo(x, y, duration=0.25)
            self._set_status(
                f"Mouse at result {index + 1} of {len(self._results)}"
                f"  →  screen ({x}, {y})",
                "green",
            )
        except pyautogui.FailSafeException:
            self._set_status("Failsafe: mouse was in a screen corner.", "red")
        except Exception as exc:
            self._set_status(f"Mouse error: {exc}", "red")

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
