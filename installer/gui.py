"""Branded Tkinter installer UI for Namma Agent.

Screens: Welcome (big wordmark + Start) -> Progress (live log while it installs
deps, gets the source, builds the venv) -> Provider (pick brain + key) ->
Onboarding (name, DOB, what you do, …) -> Done (Launch). Tkinter ships with
CPython, so the frozen installer needs no extra runtime.
"""
from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

from installer import core

BRAND = "#b0623a"       # warm terracotta accent
INK = "#2b2825"
PAPER = "#faf9f5"

# Mirrors namma_agent.core.setup_wizard.PROVIDER_PRESETS (kept local — the app
# package isn't importable until it's installed).
PROVIDERS = [
    ("anthropic", "Anthropic (Claude)", "claude-opus-4-8", True, ""),
    ("openai", "OpenAI (GPT)", "gpt-4o", True, ""),
    ("google", "Google (Gemini)", "gemini-2.0-flash", True, ""),
    ("ollama", "Ollama (local, no key)", "llama3.1", False, "http://localhost:11434/v1"),
    ("lmstudio", "LM Studio (local, no key)", "local-model", False, "http://localhost:1234/v1"),
    ("openai_compat", "OpenAI-compatible (custom URL)", "", True, ""),
]
ONBOARDING = [
    ("name", "Your name"),
    ("date_of_birth", "Date of birth (optional)"),
    ("occupation", "What do you do (work / study)"),
    ("location", "Where are you based"),
    ("interests", "A few interests or hobbies"),
]


class Installer(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Namma Agent Installer")
        self.configure(bg=PAPER)
        self.geometry("640x560")
        self.minsize(560, 520)
        self.install_dir = core.default_install_dir()
        self._provider = {}
        self._log_q: queue.Queue[str] = queue.Queue()
        self.body = tk.Frame(self, bg=PAPER)
        self.body.pack(fill="both", expand=True, padx=28, pady=24)
        self.show_welcome()

    # ── helpers ──────────────────────────────────────────────────────────────
    def _clear(self):
        for w in self.body.winfo_children():
            w.destroy()

    def _wordmark(self, parent):
        big = tkfont.Font(family="Georgia", size=46, weight="bold")
        tk.Label(parent, text="Namma Agent", font=big, fg=BRAND, bg=PAPER).pack(pady=(8, 2))
        tk.Label(parent, text="Intelligence for Everyone.",
                 font=tkfont.Font(family="Georgia", size=15, slant="italic"),
                 fg=INK, bg=PAPER).pack(pady=(0, 18))

    def _button(self, parent, text, cmd):
        b = tk.Button(parent, text=text, command=cmd, font=tkfont.Font(size=12, weight="bold"),
                      bg=BRAND, fg="white", activebackground=INK, activeforeground="white",
                      relief="flat", padx=22, pady=10, cursor="hand2", bd=0)
        return b

    # ── screen 1: welcome ────────────────────────────────────────────────────
    def show_welcome(self):
        self._clear()
        self._wordmark(self.body)
        tk.Label(self.body, text="Your Trusted AI Companion.  Your Agent, Your Advantage.",
                 font=tkfont.Font(size=10), fg="#7a736b", bg=PAPER).pack(pady=(0, 24))
        tk.Label(self.body, text="This will set up Namma Agent on your computer:",
                 font=tkfont.Font(size=11), fg=INK, bg=PAPER).pack(anchor="w")
        for line in ("• Install Python, Git and Node.js if they're missing",
                     "• Download the app to your Desktop",
                     "• Create its environment and install everything",
                     "• Help you pick an AI provider and answer a few quick questions"):
            tk.Label(self.body, text=line, font=tkfont.Font(size=10), fg="#4b463f", bg=PAPER).pack(anchor="w")
        tk.Label(self.body, text=f"\nInstall location:  {self.install_dir}",
                 font=tkfont.Font(size=9), fg="#7a736b", bg=PAPER).pack(anchor="w", pady=(8, 18))
        self._button(self.body, "Start installation  →", self.show_progress).pack(pady=6)

    # ── screen 2: progress ───────────────────────────────────────────────────
    def show_progress(self):
        self._clear()
        tk.Label(self.body, text="Installing Namma Agent…", font=tkfont.Font(family="Georgia", size=20, weight="bold"),
                 fg=BRAND, bg=PAPER).pack(anchor="w", pady=(0, 10))
        bar = ttk.Progressbar(self.body, mode="indeterminate"); bar.pack(fill="x"); bar.start(12)
        self._log = tk.Text(self.body, height=16, bg="#1e1c1a", fg="#e8e3da", insertbackground="#e8e3da",
                            relief="flat", font=tkfont.Font(family="Consolas", size=9), wrap="word")
        self._log.pack(fill="both", expand=True, pady=14)
        threading.Thread(target=self._do_bootstrap, daemon=True).start()
        self.after(120, lambda: self._drain_log(bar))

    def _log_cb(self, msg: str):
        self._log_q.put(msg)

    def _drain_log(self, bar):
        try:
            while True:
                msg = self._log_q.get_nowait()
                if msg == "__DONE__":
                    bar.stop(); self.show_provider(); return
                if msg.startswith("__ERR__"):
                    bar.stop(); self._fail(msg[7:]); return
                self._log.insert("end", msg + "\n"); self._log.see("end")
        except queue.Empty:
            pass
        self.after(150, lambda: self._drain_log(bar))

    def _do_bootstrap(self):
        try:
            core.bootstrap(self.install_dir, self._log_cb)
            self._log_q.put("__DONE__")
        except Exception as exc:  # noqa: BLE001
            self._log_q.put(f"__ERR__{exc}")

    def _fail(self, msg):
        tk.Label(self.body, text=f"Install failed: {msg}", fg="#b00020", bg=PAPER,
                 wraplength=560, font=tkfont.Font(size=10)).pack(anchor="w", pady=8)
        self._button(self.body, "Close", self.destroy).pack(pady=6)

    # ── screen 3: provider ───────────────────────────────────────────────────
    def show_provider(self):
        self._clear()
        tk.Label(self.body, text="Choose your AI provider", font=tkfont.Font(family="Georgia", size=20, weight="bold"),
                 fg=BRAND, bg=PAPER).pack(anchor="w", pady=(0, 4))
        tk.Label(self.body, text="The 'brain'. You can change this later in Settings.",
                 font=tkfont.Font(size=10), fg="#7a736b", bg=PAPER).pack(anchor="w", pady=(0, 16))
        labels = [p[1] for p in PROVIDERS]
        self._pv = tk.StringVar(value=labels[0])
        ttk.Combobox(self.body, values=labels, textvariable=self._pv, state="readonly").pack(fill="x")

        tk.Label(self.body, text="Model", bg=PAPER, fg=INK, font=tkfont.Font(size=10)).pack(anchor="w", pady=(14, 2))
        self._model = tk.Entry(self.body); self._model.pack(fill="x")
        tk.Label(self.body, text="API key (leave blank for local providers)", bg=PAPER, fg=INK,
                 font=tkfont.Font(size=10)).pack(anchor="w", pady=(14, 2))
        self._key = tk.Entry(self.body, show="•"); self._key.pack(fill="x")
        self._base = tk.Entry(self.body)  # only shown for openai_compat

        def on_pick(*_):
            pid, _lbl, model, _needs, base = PROVIDERS[labels.index(self._pv.get())]
            self._model.delete(0, "end"); self._model.insert(0, model)
            if pid == "openai_compat":
                tk.Label(self.body, text="Base URL", bg=PAPER, fg=INK).pack(anchor="w")
                self._base.pack(fill="x")
            else:
                self._base.pack_forget()
        self._pv.trace_add("write", on_pick); on_pick()

        self._button(self.body, "Save provider  →", self._save_provider).pack(pady=22)

    def _save_provider(self):
        pid, _lbl, _model, _needs, _base = PROVIDERS[[p[1] for p in PROVIDERS].index(self._pv.get())]
        prov = {"type": pid, "model": self._model.get().strip()}
        if self._key.get().strip():
            prov["api_key"] = self._key.get().strip()
        if pid == "openai_compat" and self._base.get().strip():
            prov["base_url"] = self._base.get().strip()
        threading.Thread(target=lambda: core.write_provider(self.install_dir, prov), daemon=True).start()
        self.show_onboarding()

    # ── screen 4: onboarding ─────────────────────────────────────────────────
    def show_onboarding(self):
        self._clear()
        tk.Label(self.body, text="Tell Namma Agent about you", font=tkfont.Font(family="Georgia", size=20, weight="bold"),
                 fg=BRAND, bg=PAPER).pack(anchor="w", pady=(0, 4))
        tk.Label(self.body, text="Optional — so it knows you from the first chat. Skip any.",
                 font=tkfont.Font(size=10), fg="#7a736b", bg=PAPER).pack(anchor="w", pady=(0, 14))
        self._fields = {}
        for key, label in ONBOARDING:
            tk.Label(self.body, text=label, bg=PAPER, fg=INK, font=tkfont.Font(size=10)).pack(anchor="w", pady=(8, 2))
            e = tk.Entry(self.body); e.pack(fill="x"); self._fields[key] = e
        self._button(self.body, "Finish  →", self._finish).pack(pady=22)

    def _finish(self):
        answers = {k: e.get().strip() for k, e in self._fields.items() if e.get().strip()}
        if answers:
            threading.Thread(target=lambda: core.write_onboarding(self.install_dir, answers), daemon=True).start()
        self.show_done()

    # ── screen 5: done ───────────────────────────────────────────────────────
    def show_done(self):
        self._clear()
        self._wordmark(self.body)
        tk.Label(self.body, text="You're all set 🎉", font=tkfont.Font(family="Georgia", size=18, weight="bold"),
                 fg=INK, bg=PAPER).pack(pady=(6, 6))
        tk.Label(self.body, text=f"Installed to {self.install_dir}", font=tkfont.Font(size=9),
                 fg="#7a736b", bg=PAPER).pack(pady=(0, 20))
        self._button(self.body, "Launch Namma Agent", self._launch).pack(pady=6)
        tk.Button(self.body, text="Close", command=self.destroy, relief="flat", bg=PAPER,
                  fg="#7a736b", cursor="hand2", bd=0).pack(pady=4)

    def _launch(self):
        core.launch(self.install_dir)
        self.destroy()


def main():
    Installer().mainloop()


if __name__ == "__main__":
    main()
