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
# tiny module; `cwatm.run_cwatm` is not, it drags in pandas/netCDF4.
HEAVY = {
    "xarray", "rasterio", "plotly", "folium", "netCDF4", "pandas",
    "matplotlib", "flopy", "branca", "openpyxl",
    # CWatM account: only src/gui/utils/account_client.py may import these, lazily.
    "supabase", "supabase_auth", "postgrest", "pydantic", "keyring",
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
    "src/gui/components/account_ui.py",
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


_SHELL_CALLS = {("os", "system"), ("os", "popen"), ("subprocess", "getoutput"),
                ("subprocess", "getstatusoutput")}
_SUBPROCESS_RUNNERS = {"Popen", "run", "call", "check_call", "check_output"}


def shell_problems(path, tree):
    """Programs are started with an argument LIST, never through a shell (security
    review, bandit B602/B605/B607): no shell=True, no os.system/os.popen/getoutput,
    and no subprocess call whose command is one string (that is shell parsing on
    POSIX and command-line re-parsing on Windows)."""
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for kw in node.keywords:
            if kw.arg == "shell" and not (isinstance(kw.value, ast.Constant)
                                          and kw.value.value is False):
                out.append(f"{path}:{node.lineno}: shell=... - pass an argument list "
                           f"and never use a shell")
        f = node.func
        if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
            pair = (f.value.id, f.attr)
            if pair in _SHELL_CALLS:
                out.append(f"{path}:{node.lineno}: {pair[0]}.{pair[1]}() runs a shell - "
                           f"use subprocess with an argument list (or QProcess)")
            if f.value.id == "subprocess" and f.attr in _SUBPROCESS_RUNNERS and \
                    node.args and isinstance(node.args[0], (ast.Constant, ast.JoinedStr,
                                                            ast.BinOp)):
                out.append(f"{path}:{node.lineno}: subprocess.{f.attr}() with one command "
                           f"string - pass a list of arguments")
    return out


import re as _re

_UNSAFE_LOADERS = {("pickle", "load"), ("pickle", "loads"), ("marshal", "load"),
                   ("marshal", "loads"), ("shelve", "open"), ("yaml", "unsafe_load"),
                   ("yaml", "full_load")}
_RICH_TEXT_CALLS = {"setHtml", "insertHtml", "setMarkdown", "appendHtml"}
_SECRET_RE = _re.compile(r"sb_secret_[A-Za-z0-9_-]{8,}"
                         r"|eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.")


def content_problems(path, tree, raw):
    """sast.md step 4 - four rules, GUI code only:
    a) no pickle / marshal / shelve / unsafe yaml for reading data (running code
       hidden in a file); yaml.load only with a Safe loader;
    b) no verify=False (switching off TLS certificate checks);
    c) no Supabase secret key / JWT literal in the code (gitleaks checks too);
    d) every rich-text sink (setHtml / insertHtml / setMarkdown / appendHtml) carries
       a '# html-safe: <reason>' note, and setOpenExternalLinks(True) is not used -
       links go through open_path.make_links_safe()."""
    out = []
    lines = raw.split("\n")

    def noted(lineno):
        here = lines[lineno - 1] if lineno - 1 < len(lines) else ""
        before = lines[lineno - 2] if lineno >= 2 else ""
        return "html-safe:" in here or "html-safe:" in before

    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and _SECRET_RE.search(node.value):
            out.append(f"{path}:{node.lineno}: a secret key / JWT literal - secrets "
                       f"never belong in the GUI")
        if not isinstance(node, ast.Call):
            continue
        for kw in node.keywords:
            if kw.arg == "verify" and isinstance(kw.value, ast.Constant) \
                    and kw.value.value is False:
                out.append(f"{path}:{node.lineno}: verify=False switches off the TLS "
                           f"certificate check")
        f = node.func
        if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
            pair = (f.value.id, f.attr)
            if pair in _UNSAFE_LOADERS:
                out.append(f"{path}:{node.lineno}: {pair[0]}.{pair[1]}() can run code "
                           f"hidden in the data - use json / a safe loader")
            if pair == ("yaml", "load") and not any(
                    kw.arg == "Loader" and "Safe" in ast.unparse(kw.value)
                    for kw in node.keywords):
                out.append(f"{path}:{node.lineno}: yaml.load() without a Safe loader - "
                           f"use yaml.safe_load()")
        if isinstance(f, ast.Attribute):
            if f.attr in _RICH_TEXT_CALLS and not noted(node.lineno):
                out.append(f"{path}:{node.lineno}: {f.attr}() renders rich text - escape "
                           f"outside text and add '# html-safe: <reason>'")
            if f.attr == "setOpenExternalLinks" and node.args and \
                    isinstance(node.args[0], ast.Constant) and node.args[0].value is True:
                out.append(f"{path}:{node.lineno}: setOpenExternalLinks(True) hands any "
                           f"link to the desktop (a file:// link to a program runs it) - "
                           f"use open_path.make_links_safe()")
    return out


_NOSEC_RE = _re.compile(r"#\s*nosec\b(.*)$")


def nosec_problems(path, raw):
    """A Bandit '# nosec' must name the check(s) it silences ('# nosec B110') and
    have its reason on the line above ('# B110 accepted: <why>') - never a bare
    '# nosec', which would silence every check on that line, unexplained (sast.md)."""
    import io
    import tokenize
    out = []
    lines = raw.split("\n")
    comments = {}                       # line index -> comment text (real comments only)
    try:
        for tok in tokenize.generate_tokens(io.StringIO(raw).readline):
            if tok.type == tokenize.COMMENT:
                comments[tok.start[0] - 1] = tok.string
    except (tokenize.TokenError, SyntaxError):
        return out
    for i, comment in sorted(comments.items()):
        m = _NOSEC_RE.search(comment)
        if not m:
            continue
        ids = _re.findall(r"\bB\d{3}\b", m.group(1))
        if not ids:
            out.append(f"{path}:{i + 1}: bare '# nosec' - name the check, e.g. "
                       f"'# nosec B110'")
            continue
        above = lines[i - 1] if i else ""
        for tid in ids:
            if f"{tid} accepted:" not in above:
                out.append(f"{path}:{i + 1}: '# nosec {tid}' needs its reason on the "
                           f"line above: '# {tid} accepted: <why>'")
    return out


def check():
    problems = []

    # 0. No shell, and the step-4 content rules, in the GUI's own code (also the two
    #    entry scripts); and every Bandit suppression named and explained (also in
    #    tools/).
    for path in list(py_files(SRC)) + ["cwatm_gui.py", "cwatm_model.py"]:
        if os.path.exists(path):
            raw = open(path, encoding="utf-8").read()
            tree = ast.parse(raw)
            problems += shell_problems(path, tree)
            problems += content_problems(path, tree, raw)
    for path in list(py_files(SRC)) + list(py_files("tools")) + [
            "cwatm_gui.py", "cwatm_model.py"]:
        if os.path.exists(path):
            problems += nosec_problems(path, open(path, encoding="utf-8").read())

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
