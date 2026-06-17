"""
Cross-platform desktop notifications — best-effort and non-blocking.

After a long batch job a user may have switched to another window. notify() pops
a native OS notification so they know the work is done without watching the bar.

Contract:
  • Never raises and never blocks: the actual delivery runs on a daemon thread.
  • If no backend is available it's a silent no-op.

Backends, in order of attempt per platform:
  Linux   → notify-send (libnotify; present on virtually every desktop)
  macOS   → osascript "display notification"
  Windows → PowerShell toast via Windows.UI.Notifications
"""
from __future__ import annotations

import platform
import shutil
import subprocess
import threading


def notify(title: str, message: str) -> None:
    """Show a desktop notification. Fire-and-forget; safe to call from any thread."""
    threading.Thread(target=_deliver, args=(title, message), daemon=True).start()


def _deliver(title: str, message: str) -> None:
    try:
        system = platform.system()
        if system == "Linux":
            _linux(title, message)
        elif system == "Darwin":
            _macos(title, message)
        elif system == "Windows":
            _windows(title, message)
    except Exception:
        pass


def _run(cmd: list[str]) -> None:
    # NO_WINDOW stops the Windows PowerShell toast backend from flashing a
    # console window every time a batch finishes.
    from common.proc import NO_WINDOW
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   timeout=10, **NO_WINDOW)


def _linux(title: str, message: str) -> None:
    if shutil.which("notify-send"):
        _run(["notify-send", "-a", "Multimedia Master", title, message])


def _macos(title: str, message: str) -> None:
    if shutil.which("osascript"):
        # Escape double quotes to keep the AppleScript string well-formed.
        t = title.replace('"', '\\"')
        m = message.replace('"', '\\"')
        _run(["osascript", "-e",
              f'display notification "{m}" with title "{t}"'])


def _windows(title: str, message: str) -> None:
    # PowerShell toast — no third-party dependency needed.
    t = title.replace("'", "''")
    m = message.replace("'", "''")
    script = (
        "[Windows.UI.Notifications.ToastNotificationManager, "
        "Windows.UI.Notifications, ContentType = WindowsRuntime] > $null; "
        "$xml = [Windows.UI.Notifications.ToastNotificationManager]::"
        "GetTemplateContent("
        "[Windows.UI.Notifications.ToastTemplateType]::ToastText02); "
        "$t = $xml.GetElementsByTagName('text'); "
        f"$t[0].AppendChild($xml.CreateTextNode('{t}')) > $null; "
        f"$t[1].AppendChild($xml.CreateTextNode('{m}')) > $null; "
        "$toast = [Windows.UI.Notifications.ToastNotification]::new($xml); "
        "[Windows.UI.Notifications.ToastNotificationManager]::"
        "CreateToastNotifier('Multimedia Master').Show($toast);"
    )
    _run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script])
