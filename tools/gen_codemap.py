"""Generates .claude/CODEMAP.md: every source file with its public classes/functions and the first sentence of their docs.

Python is read with ast (docstrings); C# with regexes (/// <summary> comments). Test files are listed with a test count only.
Run `python tools/gen_codemap.py` after changing code; `--check` exits 1 if the committed map is stale.
"""

import ast
import html
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
OUT = ROOT / ".claude" / "CODEMAP.md"
PY_DIRS = ["src", "tests", "tools"]
CS_DIRS = ["csharp/src", "csharp/tests"]
MAX_DOC = 200


def first_sentence(doc):
    """First sentence of the first paragraph, whitespace collapsed, capped at MAX_DOC characters."""
    if not doc:
        return ""
    text = " ".join(doc.strip().split("\n\n")[0].split())
    match = re.search(r"(?<!e\.g)(?<!i\.e)[.!?](\s|$)", text)
    text = text[:match.end()].strip() if match else text
    return text if len(text) <= MAX_DOC else text[:MAX_DOC - 3].rstrip() + "..."


def py_signature(node):
    args = node.args
    names = [a.arg for a in args.posonlyargs + args.args if a.arg not in ("self", "cls")]
    if args.vararg:
        names.append("*" + args.vararg.arg)
    names += [a.arg for a in args.kwonlyargs]
    if args.kwarg:
        names.append("**" + args.kwarg.arg)
    return f"{node.name}({', '.join(names)})"


def py_entry(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    lines = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
            lines.append((py_signature(node), first_sentence(ast.get_docstring(node)), []))
        elif isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            methods = [(py_signature(m), first_sentence(ast.get_docstring(m)), []) for m in node.body
                       if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)) and not m.name.startswith("_")]
            lines.append((f"class {node.name}", first_sentence(ast.get_docstring(node)), methods))
    is_script = any(isinstance(n, ast.If) and "__main__" in ast.unparse(n.test) for n in tree.body)
    desc = first_sentence(ast.get_docstring(tree))
    return (desc + (" (runnable)" if is_script else "")).strip(), lines


TYPE_RE = re.compile(r"^\s*((?:(?:public|internal|private|protected|static|sealed|abstract|partial|readonly|file)\s+)*)"
                     r"(record\s+struct|record\s+class|record|class|struct|interface|enum)\s+(\w+)")
MEMBER_START_RE = re.compile(r"^\s+public\s")


def cs_doc_text(lines):
    text = " ".join(line.strip()[3:].strip() for line in lines)
    text = re.sub(r'<(?:see|seealso)\s+cref="([^"]+)"\s*/>', r"\1", text)
    text = re.sub(r'<(?:paramref|typeparamref)\s+name="([^"]+)"\s*/>', r"\1", text)
    text = re.sub(r"<param\b.*", "", text)  # parameter docs follow the summary; keep the summary only
    return html.unescape(re.sub(r"<[^>]+>", "", text))


def balanced(lines, start):
    """Text from lines[start] on until parentheses balance (a signature can wrap over several lines)."""
    text, depth, i = "", 0, start
    while i < len(lines):
        text += " " + lines[i].strip()
        depth += lines[i].count("(") - lines[i].count(")")
        if depth <= 0 and "(" in text:
            break
        if "(" not in text:
            break
        i += 1
    return " ".join(text.split())


def cs_signature(text):
    """Declaration up to the parameter list's closing parenthesis, without access modifiers or body.

    The parameter list is the first '(' glued to a name (`Gain(`, `Foo<T>(`), which skips a tuple return type like `(double Mean, ...)`.
    """
    start = next((m.end() - 1 for m in re.finditer(r"[\w>]\(", text)), None)
    if start is None:
        sig = re.split(r"\s*(?:[{:;]|=>|\bwhere\b)", text)[0]
    else:
        depth, end = 0, len(text)
        for i in range(start, len(text)):
            depth += {"(": 1, ")": -1}.get(text[i], 0)
            if depth == 0:
                end = i + 1
                break
        sig = text[:end]
    sig = re.sub(r"\(\s+", "(", sig)
    return re.sub(r"\b(public|internal|sealed|partial|readonly|override|virtual)\s+", "", sig).strip()


def opens_body(lines, start):
    """True if the declaration at lines[start] has a { body } rather than ending in ';' (a positional record)."""
    for line in lines[start:]:
        for ch in line.split("//")[0]:
            if ch in "{;":
                return ch == "{"
    return False


def cs_entry(path):
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    if not any(re.match(r"\s*namespace\s", line) for line in lines):
        commands = re.findall(r'^\s*case\s+"([\w-]+)":', "\n".join(lines), re.M)
        return "Top-level program" + (f"; commands: {', '.join(commands)}" if commands else ""), []
    types, doc, stack, depth = [], [], [], 0  # stack: [item, depth before its body, body entered]
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("///"):
            doc.append(line)
            continue
        current = stack[-1][0] if stack else None
        type_match = TYPE_RE.match(line)
        if stripped and not stripped.startswith("["):
            if type_match and "private" not in type_match.group(1) and "protected" not in type_match.group(1):
                item = (cs_signature(balanced(lines, i)), first_sentence(cs_doc_text(doc)), [])
                types.append(item)
                if opens_body(lines, i):
                    stack.append([item, depth, False])
            elif current is not None and (MEMBER_START_RE.match(line) or current[0].startswith("interface")) \
                    and "(" in line.split("=>")[0].split("=")[0] and not stripped.startswith(("//", "return", "var ")):
                current[2].append((cs_signature(balanced(lines, i)), first_sentence(cs_doc_text(doc)), []))
            doc = []
        code = re.sub(r'"(?:\\.|[^"\\])*"', "", line.split("//")[0])
        depth += code.count("{") - code.count("}")
        for entry in stack:
            entry[2] = entry[2] or depth > entry[1]
        while stack and stack[-1][2] and depth <= stack[-1][1]:
            stack.pop()
    return "", types


def test_count(path):
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix == ".py":
        return len(re.findall(r"^\s*def test_", text, re.M))
    return len(re.findall(r"\[(?:Fact|Theory)\b", text))


def is_test(path):
    return "tests" in path.relative_to(ROOT).parts


def render_items(items, indent):
    out = []
    for sig, doc, children in items:
        out.append(f"{'  ' * indent}- `{sig}`" + (f": {doc}" if doc else ""))
        out += render_items(children, indent + 1)
    return out


def render():
    out = ["# Code map", "",
           "Generated by `tools/gen_codemap.py` from docstrings and `///` summaries; do not edit by hand.",
           "Regenerate with `python tools/gen_codemap.py` after adding, renaming or re-documenting code.",
           "Data files, `archive/` and build output are not listed.", ""]
    files = [p for d in PY_DIRS for p in (ROOT / d).rglob("*.py")] + \
            [p for d in CS_DIRS for p in (ROOT / d).rglob("*.cs") if not {"bin", "obj"} & set(p.parts)]
    files = sorted(p for p in files if p.name != "__init__.py")
    by_dir = {}
    for path in files:
        by_dir.setdefault(path.parent.relative_to(ROOT).as_posix(), []).append(path)
    for directory, paths in by_dir.items():
        out += [f"## {directory}/", ""]
        for path in paths:
            n_lines = len(path.read_text(encoding="utf-8-sig").splitlines())
            if is_test(path):
                count = test_count(path)
                out.append(f"- **{path.name}** ({n_lines} lines): " + (f"{count} tests" if count else "shared fixtures"))
                continue
            desc, items = py_entry(path) if path.suffix == ".py" else cs_entry(path)
            out.append(f"- **{path.name}** ({n_lines} lines)" + (f": {desc}" if desc else ""))
            out += render_items(items, 1)
        out.append("")
    return "\n".join(out)


if __name__ == "__main__":
    text = render()
    if "--check" in sys.argv:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != text:
            print(f"{OUT.relative_to(ROOT)} is stale: run python tools/gen_codemap.py")
            sys.exit(1)
        sys.exit(0)
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {OUT.relative_to(ROOT)} ({len(text.splitlines())} lines)")
