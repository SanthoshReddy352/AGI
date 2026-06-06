import importlib.util
import os
import platform
import re
import shlex
import shutil
from dataclasses import dataclass, field

from core.logger import logger


KNOWN_PYTHON_MODULES = (
    "cv2",
    "torch",
    "ultralytics",
    "selenium",
    "webdriver_manager",
    "google.genai",
    "dotenv",
    "llama_cpp",
    "sounddevice",
    "PyQt6",
    "PyQt5",
)

KNOWN_BINARIES = (
    "firefox",
    "firefox-esr",
    "google-chrome",
    "google-chrome-stable",
    "brave-browser",
    "brave-browser-stable",
    "chromium",
    "nautilus",
    "thunar",
    "gnome-calculator",
    "mate-calc",
    "gnome-terminal",
    "qterminal",
    "x-terminal-emulator",
    "mpv",
    "vlc",
    "wpctl",
    "pactl",
    "amixer",
    "xdg-open",
)


@dataclass
class DesktopApp:
    name: str
    command: str
    desktop_id: str = ""
    exec_line: str = ""
    aliases: set[str] = field(default_factory=set)
    # Track 6.1: where this row was discovered. One of
    # binary|desktop|lnk|registry. Used by AppIndexStore so a future
    # re-scan can supersede stale rows by source.
    source: str = "desktop"
    # Track 6.1: free-form categories. On Linux this is the `.desktop`
    # file's Categories= field; on Windows we use Start Menu subfolder
    # names. Used (eventually) for "open my web apps"-style routing.
    categories: list[str] = field(default_factory=list)


class SystemCapabilities:
    def __init__(self, config=None):
        self.config = config
        self.platform = platform.system()
        self.python_modules = {}
        self.binaries = {}
        self.desktop_apps = {}
        self.audio_backends = []
        self.skill_status = {}

    def probe(self):
        self.python_modules = {
            module_name: self._module_available(module_name)
            for module_name in KNOWN_PYTHON_MODULES
        }
        self.binaries = {
            binary: shutil.which(binary)
            for binary in KNOWN_BINARIES
        }
        self.desktop_apps = self._discover_desktop_apps()
        self.audio_backends = [
            backend for backend in ("wpctl", "pactl", "amixer")
            if self.binaries.get(backend)
        ]
        logger.info(
            "Capability probe complete: platform=%s, audio_backends=%s, desktop_apps=%s",
            self.platform,
            ", ".join(self.audio_backends) or "none",
            len(self.desktop_apps),
        )
        return self

    def register_skill_status(self, skill_name, available, reason="", tools=None):
        self.skill_status[skill_name] = {
            "available": bool(available),
            "reason": (reason or "").strip(),
            "tools": list(tools or []),
        }

    def missing_python_modules(self, required):
        return [name for name in (required or []) if not self.python_modules.get(name)]

    def missing_binaries(self, required):
        return [name for name in (required or []) if not self.binaries.get(name)]

    def disabled_skills(self):
        return {
            name: info["reason"] or "Unavailable on this system."
            for name, info in self.skill_status.items()
            if not info.get("available")
        }

    def summary_lines(self):
        disabled = self.disabled_skills()
        lines = [
            f"Platform: {self.platform}",
            f"Audio backends: {', '.join(self.audio_backends) if self.audio_backends else 'none'}",
            f"Desktop apps: {len(self.desktop_apps)} discovered",
        ]
        if disabled:
            lines.append(f"Disabled skills: {len(disabled)}")
        return lines

    def _module_available(self, module_name):
        try:
            return importlib.util.find_spec(module_name) is not None
        except ModuleNotFoundError:
            return False
        except Exception:
            return False

    def _discover_desktop_apps(self):
        apps = {}
        seen = set()

        for binary, resolved in self.binaries.items():
            if not resolved:
                continue
            alias = self._normalize_alias(os.path.basename(binary))
            apps[alias] = DesktopApp(
                name=self._prettify_name(alias),
                command=binary,
                aliases={alias},
                source="binary",
            )
            seen.add(binary)

        for applications_dir in self._application_dirs():
            if not os.path.isdir(applications_dir):
                continue

            if self.platform == "Windows":
                self._scan_windows_start_menu(applications_dir, apps, seen)
            else:
                self._scan_linux_applications(applications_dir, apps, seen)

        if self.platform == "Windows":
            self._scan_windows_uninstall_registry(apps, seen)

        return apps

    def _scan_linux_applications(self, applications_dir, apps, seen):
        for entry_name in sorted(os.listdir(applications_dir)):
            if not entry_name.endswith(".desktop"):
                continue
            entry_path = os.path.join(applications_dir, entry_name)
            app = self._parse_desktop_file(entry_path)
            if not app or not app.command:
                continue

            key = self._normalize_alias(app.name or app.desktop_id or app.command)
            existing = apps.get(key)
            if existing:
                existing.aliases.update(app.aliases)
                if not existing.exec_line:
                    existing.exec_line = app.exec_line
                # Categories accumulate across upstream/user .desktop files
                merged_categories = set(existing.categories) | set(app.categories)
                existing.categories = sorted(merged_categories)
                continue

            apps[key] = app
            seen.add(app.command)

    def _scan_windows_start_menu(self, applications_dir, apps, seen):
        for root, _, files in os.walk(applications_dir):
            for entry_name in files:
                if not entry_name.endswith(".lnk"):
                    continue
                entry_path = os.path.join(root, entry_name)
                app = self._parse_lnk_file(entry_path, start_menu_root=applications_dir)
                if not app:
                    continue

                key = self._normalize_alias(app.name)
                existing = apps.get(key)
                if existing:
                    existing.aliases.update(app.aliases)
                    merged_categories = set(existing.categories) | set(app.categories)
                    existing.categories = sorted(merged_categories)
                    continue

                apps[key] = app
                seen.add(app.command)

    def _scan_windows_uninstall_registry(self, apps, seen):
        try:
            import winreg  # type: ignore  # noqa: PLC0415
        except ImportError:
            return
        hives = (
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        )
        for hive, subkey in hives:
            try:
                self._walk_uninstall_hive(winreg, hive, subkey, apps, seen)
            except OSError as exc:
                logger.debug("Skipping registry hive %s: %s", subkey, exc)

    def _walk_uninstall_hive(self, winreg, hive, subkey, apps, seen):
        with winreg.OpenKey(hive, subkey) as root_key:
            i = 0
            while True:
                try:
                    name = winreg.EnumKey(root_key, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(root_key, name) as item:
                        app = self._app_from_uninstall_key(winreg, item)
                except OSError:
                    continue
                if not app:
                    continue
                key = self._normalize_alias(app.name)
                existing = apps.get(key)
                if existing:
                    existing.aliases.update(app.aliases)
                    continue
                apps[key] = app
                seen.add(app.command)

    def _app_from_uninstall_key(self, winreg, item) -> "DesktopApp | None":
        display_name = self._read_reg_value(winreg, item, "DisplayName")
        if not display_name or "uninstall" in display_name.lower():
            return None
        if self._read_reg_value(winreg, item, "SystemComponent") == 1:
            return None
        display_icon = self._read_reg_value(winreg, item, "DisplayIcon") or ""
        install_location = self._read_reg_value(winreg, item, "InstallLocation") or ""
        command = self._best_registry_command(display_icon, install_location, display_name)
        if not command:
            return None
        aliases = {self._normalize_alias(display_name)}
        aliases.discard("")
        return DesktopApp(
            name=display_name,
            command=command,
            desktop_id=display_name,
            exec_line=command,
            aliases=aliases,
            source="registry",
        )

    def _read_reg_value(self, winreg, item, name):
        try:
            value, _ = winreg.QueryValueEx(item, name)
        except OSError:
            return None
        return value

    def _best_registry_command(self, display_icon, install_location, display_name):
        icon = (display_icon or "").split(",", 1)[0].strip().strip('"')
        if icon.lower().endswith(".exe") and os.path.isfile(icon):
            return icon
        if install_location:
            candidate = self._first_exe_in_dir(install_location, display_name)
            if candidate:
                return candidate
        return icon or ""

    def _first_exe_in_dir(self, directory, display_name):
        try:
            entries = os.listdir(directory)
        except OSError:
            return ""
        prefer = self._normalize_alias(display_name).split(" ")[0]
        exe_files = [e for e in entries if e.lower().endswith(".exe")]
        if not exe_files:
            return ""
        for exe in exe_files:
            if prefer and prefer in exe.lower():
                return os.path.join(directory, exe)
        return os.path.join(directory, exe_files[0])

    def _application_dirs(self):
        if self.platform == "Windows":
            return (
                os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs"),
                os.path.expandvars(r"%ALLUSERSPROFILE%\Microsoft\Windows\Start Menu\Programs"),
            )
        return (
            "/usr/share/applications",
            os.path.expanduser("~/.local/share/applications"),
        )

    def _parse_lnk_file(self, path, start_menu_root=""):
        name = os.path.splitext(os.path.basename(path))[0]
        if "uninstall" in name.lower():
            return None

        # Track 6.1: try to resolve to the real .exe target. Falls back to
        # the .lnk path itself if pywin32 is unavailable — os.startfile
        # follows .lnk on Windows, so launching still works either way.
        resolved_target = self._resolve_lnk_target(path)
        command = resolved_target or path

        desktop_id = os.path.basename(path)
        aliases = {self._normalize_alias(name)}
        if resolved_target:
            aliases.add(self._normalize_alias(os.path.splitext(os.path.basename(resolved_target))[0]))
        aliases.discard("")

        categories = []
        if start_menu_root:
            relative = os.path.relpath(os.path.dirname(path), start_menu_root)
            if relative and relative != ".":
                categories = [p for p in relative.replace("\\", "/").split("/") if p]

        return DesktopApp(
            name=name,
            command=command,
            desktop_id=desktop_id,
            exec_line=command,
            aliases=aliases,
            source="lnk",
            categories=categories,
        )

    def _resolve_lnk_target(self, path):
        try:
            import pythoncom  # type: ignore  # noqa: PLC0415
            from win32com.shell import shell, shellcon  # type: ignore  # noqa: PLC0415, F401
        except ImportError:
            return ""
        try:
            link = pythoncom.CoCreateInstance(
                shell.CLSID_ShellLink, None,
                pythoncom.CLSCTX_INPROC_SERVER, shell.IID_IShellLink,
            )
            link.QueryInterface(pythoncom.IID_IPersistFile).Load(path)
            target, _ = link.GetPath(shell.SLGP_UNCPRIORITY)
            return target or ""
        except Exception as exc:
            logger.debug("lnk resolution failed for %s: %s", path, exc)
            return ""

    def _parse_desktop_file(self, path):
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as handle:
                lines = handle.readlines()
        except OSError:
            return None

        fields = {}
        for raw_line in lines:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key not in fields:
                fields[key] = value.strip()

        if fields.get("NoDisplay", "").lower() == "true":
            return None

        exec_line = fields.get("Exec", "")
        command = self._extract_exec_command(exec_line)
        if not command:
            return None

        name = fields.get("Name", "")
        desktop_id = os.path.basename(path)
        aliases = {
            self._normalize_alias(name),
            self._normalize_alias(os.path.splitext(desktop_id)[0]),
            self._normalize_alias(command),
        }
        aliases.discard("")

        categories_field = fields.get("Categories", "")
        categories = [c.strip() for c in categories_field.split(";") if c.strip()]

        return DesktopApp(
            name=name or self._prettify_name(command),
            command=command,
            desktop_id=desktop_id,
            exec_line=exec_line,
            aliases=aliases,
            source="desktop",
            categories=categories,
        )

    def _extract_exec_command(self, exec_line):
        if not exec_line:
            return ""
        try:
            parts = shlex.split(exec_line)
        except ValueError:
            parts = exec_line.split()
        if not parts:
            return ""
        command = os.path.basename(parts[0])
        command = re.sub(r"%[fFuUdDnNickvm]", "", command).strip()
        return command

    def _normalize_alias(self, value):
        cleaned = re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()
        return " ".join(cleaned.split())

    def _prettify_name(self, value):
        return " ".join(part.capitalize() for part in self._normalize_alias(value).split())
