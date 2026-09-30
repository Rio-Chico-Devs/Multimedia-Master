"""
PyInstaller entry point for the PDF-Manager-only build.

The full build ships launcher.py, whose window spawns each tool as a
separate process by re-invoking the same exe with --tool <name>. The
PDF-only build has a single tool and therefore no launcher window at all:
this file goes straight to the PDF Manager.

It deliberately loads tools/pdf_manager/app.py with runpy.run_path(),
exactly the way launcher.py's --tool branch does, instead of importing it.
That keeps the two builds on ONE code path: tools/ ships as plain data in
both, each tool's bare "core"/"ui" imports resolve against its own
directory, and the PDF Manager behaves identically whether it came from
MultimediaMaster.spec's full target or its pdf target. See the spec's
module docstring for why tools/ is data and not analyzed code.
"""
import sys
from pathlib import Path

# Where tools/ actually lives. sys._MEIPASS is PyInstaller's unpacked bundle:
# a temporary directory in a onefile build, the _internal/ folder next to the
# exe in a onedir build. Neither is the directory holding the exe, so this is
# stated explicitly rather than inferred from __file__.
ROOT = Path(getattr(sys, "_MEIPASS", None) or Path(__file__).parent)
sys.path.insert(0, str(ROOT / "tools"))

if __name__ == "__main__":
    import runpy

    _app = ROOT / "tools" / "pdf_manager" / "app.py"
    try:
        runpy.run_path(str(_app), run_name="__main__")
    except Exception:
        # app.py installs the real crash logger as its very first statement,
        # so anything landing here failed *before* that — an incomplete or
        # corrupt bundle. In a windowed build that means the exe simply never
        # opens a window and writes nothing anywhere, which is impossible to
        # diagnose on a customer's machine. Record it by hand.
        import traceback
        try:
            from common.paths import crash_log_path
            _log = crash_log_path("pdf_manager")
            _log.parent.mkdir(parents=True, exist_ok=True)
            with _log.open("a", encoding="utf-8") as _f:
                _f.write("\n" + "=" * 70 + "\n")
                _f.write("STARTUP FAILURE (pdf_launcher) — bundle incomplete?\n")
                _f.write("=" * 70 + "\n")
                _f.write(f"expected: {_app}\n")
                _f.write(traceback.format_exc() + "\n")
        except Exception:
            pass
        raise
