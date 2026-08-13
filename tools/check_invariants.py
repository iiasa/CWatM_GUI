"""Check the CWatM GUI's own structural invariants. No dependencies, no Qt.

These are the rules CLAUDE.md states as always-true. They are cheap to verify and easy
to break by accident, so CI runs this on every push - but it is a plain script, so you
can also just run it:

    python tools/check_invariants.py

Exit status is 0 when everything holds, 1 otherwise (with one line per violation).
"""

import ast
import os
import sys

SRC = "src/gui"

# Heavy third-party stacks that must NOT be imported at module level on the startup
# path (CLAUDE.md "fast startup / lazy imports"). `cwatm.version` is fine - it is a
# tiny module; `cwatm.run_cwatm` is not, it drags in scipy/pandas/netCDF4.
HEAVY = {
    "xarray", "rasterio", "plotly", "folium", "netCDF4", "scipy", "pandas",
    "matplotlib", "flopy", "branca", "openpyxl",
}
HEAVY_PREFIXES = ("cwatm.run_cwatm", "cwatm.management_modules",
                  "cwatm.hydrological_modules")
# Modules imported by main_window at startup, which therefore inherit its budget.
STARTUP_MODULES = {
    "src/gui/components/main_window.py",
    "src/gui/components/menu_builder.py",
    "src/gui/components/run_controller.py",
    "src/gui/components/output_box.py",
    "src/gui/components/tab_manager.py",
    "src/gui/components/settings_check.py",
    "src/gui/components/find_replace.py",
    "src/gui/components/main_window_styles.py",
}

# Line separators that str.splitlines() breaks on but Python's tokenizer does not.
# One literal U+2029 in main_window.py silently shifted every line-based tool by a
# line; keep them out of the sources and write them as escapes instead.
EXOTIC = {
    chr(0x0B): 'U+000B VT', chr(0x0C): 'U+000C FF',
    chr(0x1C): 'U+001C FS', chr(0x1D): 'U+001D GS',
    chr(0x1E): 'U+001E RS', chr(0x85): 'U+0085 NEL',
    chr(0x2028): 'U+2028 LINE SEPARATOR',
    chr(0x2029): 'U+2029 PARAGRAPH SEPARATOR',
}


def py_files(root):
    for dirpath, _dirnames, filenames in os.walk(root):
        if "__pycache__" in dirpath:
            continue
        for name in sorted(filenames):
            if name.endswith(".py"):
                yield os.path.join(dirpath, name).replace("\\", "/")


def module_level_imports(tree):
    """(name, lineno) for every import at module level, including inside a
    module-level try/except - an optional-dependency guard still pays the cost."""
    out = []

    def visit(nodes):
        for node in nodes:
            if isinstance(node, ast.Import):
                # .extend, not `out += ...`: an augmented assignment would rebind
                # `out` as a local of visit() and break the ImportFrom branch below.
                out.extend((a.name, node.lineno) for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0 and node.module:
                    out.append((node.module, node.lineno))
            elif isinstance(node, (ast.Try, ast.If)):
                visit(node.body)
                for handler in getattr(node, "handlers", []):
                    visit(handler.body)
                visit(node.orelse)
                visit(getattr(node, "finalbody", []))

    visit(tree.body)
    return out


def check():
    problems = []

    for path in py_files(SRC):
        raw = open(path, encoding="utf-8", newline="").read()
        tree = ast.parse(raw)

        # 1. No silent `except: pass` - swallowed exceptions must reach gui.log.
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                    problems.append(
                        f"{path}:{node.lineno}: silent 'except: pass' - use "
                        f"log.debug(..., exc_info=True) so gui.log records it")

        # 2. No exotic line separators in source.
        for ch, name in EXOTIC.items():
            if ch in raw:
                line = raw[:raw.index(ch)].count("\n") + 1
                problems.append(
                    f"{path}:{line}: literal {name} in source - write it as an "
                    f"escape; str.splitlines() breaks on it and the tokenizer "
                    f"does not, so line-based tools go out of step")

        # 3. os.startfile is Windows-only - open_path() is the portable wrapper.
        if "os.startfile" in raw and not path.endswith("utils/open_path.py"):
            line = raw[:raw.index("os.startfile")].count("\n") + 1
            problems.append(
                f"{path}:{line}: os.startfile does not exist off Windows - use "
                f"src/gui/utils/open_path.py: open_path()")

        # 4. Fast startup: no heavy import at module level on the startup path.
        if path in STARTUP_MODULES:
            for name, lineno in module_level_imports(tree):
                root = name.split(".")[0]
                if root in HEAVY or name.startswith(HEAVY_PREFIXES):
                    problems.append(
                        f"{path}:{lineno}: module-level import of '{name}' on the "
                        f"startup path - import it lazily inside the method that "
                        f"needs it (CLAUDE.md fast-startup rule)")

    # 5. Every module the docs promise exists.
    for required in ("src/gui/utils/temp_page.py", "src/gui/utils/open_path.py",
                     "src/gui/utils/gui_log.py", "requirements.txt",
                     "requirements_dev.txt", "tests/conftest.py"):
        if not os.path.exists(required):
            problems.append(f"missing: {required}")

    return problems


def main():
    if not os.path.isdir(SRC):
        print(f"run me from the repo root (no {SRC}/ here)", file=sys.stderr)
        return 2
    problems = check()
    for p in problems:
        print(p)
    n = len(list(py_files(SRC)))
    if problems:
        print(f"\n{len(problems)} violation(s) across {n} files")
        return 1
    print(f"all invariants hold ({n} files checked)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
