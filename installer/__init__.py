"""Namma Agent graphical installer (branded, beginner-friendly).

This package is the *installer*, separate from the `namma_agent` app package: it
must run on a machine that doesn't have the app (or even Python) yet, so it's
frozen with PyInstaller into the native one-file installers. `core` holds the
UI-free, testable logic; `gui` is the Tkinter branded UI.
"""
