"""Analysis engine: Ruff + Bandit + AST checks, scoring, and TXT report."""
import ast
import json
import os
import subprocess
import sys
import tempfile

MAX_BYTES, MAX_LINES = 1_000_000, 5000
POINTS = {"Critical": 25, "High": 10, "Medium": 4, "Low": 1}
ORDER = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
WEIGHTS = {"quality": .25, "best_practices": .20, "security": .25,
           "error_handling": .15, "performance": .15}
LABELS = {"quality": "Code Quality", "best_practices": "Best Practices",
          "security": "Security", "error_handling": "Error Handling",
          "performance": "Performance & Maintainability"}
RISKY = {"open", "int", "float", "json.loads", "json.load", "requests.get",
         "requests.post", "os.remove", "subprocess.run"}


def finding(category, severity, source, rule, line, message, fix, snippet=""):
    return {"category": category, "severity": severity, "source": source,
            "rule": rule, "line": line, "message": message,
            "fix": fix, "snippet": snippet}


def validate(code):
    if not code or not code.strip():
        return "Please paste some code or upload a .py file."
    if len(code.encode("utf-8")) > MAX_BYTES:
        return "Code is larger than 1 MB."
    if code.count("\n") + 1 > MAX_LINES:
        return f"Code has more than {MAX_LINES} lines."
    return None


# ---------- Ruff ----------
def ruff_severity(code):
    if code == "F821":
        return "High"
    if code.startswith(("F", "B")):
        return "Medium"
    return "Low"


def ruff_category(code):
    return "quality" if code[0] in "EF" else "best_practices"


def run_ruff(path, lines):
    cmd = [sys.executable, "-m", "ruff", "check", "--isolated", "--no-cache",
           "--select", "E,F,B,N,SIM", "--output-format", "json", path]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=60).stdout
    results = []
    for i in json.loads(out):
        row = i["location"]["row"]
        results.append(finding(
            ruff_category(i["code"]), ruff_severity(i["code"]), "Ruff", i["code"],
            row, i["message"],
            f"See https://docs.astral.sh/ruff/rules/{i['code']}/",
            lines[row - 1].strip() if 0 < row <= len(lines) else ""))
    return results


# ---------- Bandit ----------
def bandit_severity(sev, conf):
    if sev == "HIGH":
        return "Critical" if conf == "HIGH" else "High"
    return "Medium" if sev == "MEDIUM" else "Low"


def run_bandit(path):
    cmd = [sys.executable, "-m", "bandit", "-f", "json", "-q", path]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=60).stdout
    return [finding("security",
                    bandit_severity(i["issue_severity"], i["issue_confidence"]),
                    "Bandit", i["test_id"], i["line_number"], i["issue_text"],
                    i.get("more_info", ""), i["code"].strip().splitlines()[0]
                    if i.get("code") else "")
            for i in json.loads(out)["results"]]


# ---------- AST ----------
LOOPS = (ast.For, ast.While, ast.AsyncFor)
BRANCH = (ast.If, ast.For, ast.While, ast.Try, ast.With, ast.AsyncFor, ast.AsyncWith)
DECISION = (ast.If, ast.For, ast.While, ast.ExceptHandler, ast.BoolOp, ast.IfExp, ast.AsyncFor)


def depth(node, d=0):
    return max([d] + [depth(c, d + (isinstance(c, BRANCH))) for c in ast.iter_child_nodes(node)])


def has_nested_loop(fn):
    for outer in ast.walk(fn):
        if isinstance(outer, LOOPS):
            if any(n is not outer and isinstance(n, LOOPS) for n in ast.walk(outer)):
                return outer
    return None


class Checker(ast.NodeVisitor):
    def __init__(self):
        self.found, self.try_depth = [], 0

    def add(self, cat, sev, rule, node, msg, fix):
        self.found.append(finding(cat, sev, "AST", rule, node.lineno, msg, fix))

    def visit_Try(self, node):
        for h in node.handlers:
            if h.type is None:
                self.add("error_handling", "Medium", "AST-BARE-EXCEPT", h,
                         "Bare 'except:' catches everything, including KeyboardInterrupt.",
                         "Catch specific exceptions, e.g. 'except ValueError:'.")
            if len(h.body) == 1 and isinstance(h.body[0], ast.Pass):
                self.add("error_handling", "Medium", "AST-EXCEPT-PASS", h,
                         "Exception is silently swallowed with 'pass'.",
                         "Log the error or handle it explicitly.")
        self.try_depth += 1
        for n in node.body:
            self.visit(n)
        self.try_depth -= 1
        for n in node.handlers + node.orelse + node.finalbody:
            self.visit(n)

    def visit_Call(self, node):
        name = ast.unparse(node.func)
        if name in RISKY and not self.try_depth:
            self.add("error_handling", "Low", "AST-RISKY-CALL", node,
                     f"'{name}()' can fail but is not inside a try block.",
                     "Wrap the call in try/except and handle the failure.")
        self.generic_visit(node)

    def visit_ClassDef(self, node):
        if not ast.get_docstring(node):
            self.add("best_practices", "Low", "AST-DOCSTRING", node,
                     f"Class '{node.name}' has no docstring.", "Add a short docstring.")
        self.generic_visit(node)

    def visit_FunctionDef(self, node):
        if not ast.get_docstring(node):
            self.add("best_practices", "Low", "AST-DOCSTRING", node,
                     f"Function '{node.name}' has no docstring.", "Add a short docstring.")
        defaults = node.args.defaults + [d for d in node.args.kw_defaults if d]
        if any(isinstance(d, (ast.List, ast.Dict, ast.Set)) for d in defaults):
            self.add("best_practices", "Medium", "AST-MUTABLE-DEFAULT", node,
                     f"'{node.name}' uses a mutable default argument.",
                     "Use None as the default and create the object inside the function.")
        length = (node.end_lineno or node.lineno) - node.lineno + 1
        if length > 50:
            self.add("performance", "Low", "AST-LONG-FUNCTION", node,
                     f"'{node.name}' is {length} lines long.", "Split it into smaller functions.")
        if depth(node) > 4:
            self.add("performance", "Low", "AST-DEEP-NESTING", node,
                     f"'{node.name}' has deeply nested blocks.", "Use early returns or helper functions.")
        loop = has_nested_loop(node)
        if loop:
            self.add("performance", "Low", "AST-NESTED-LOOP", loop,
                     "Nested loops can be slow on large inputs (O(n²)).",
                     "Consider a dict/set lookup or a different algorithm.")
        cx = 1 + sum(isinstance(n, DECISION) for n in ast.walk(node))
        if cx > 10:
            self.add("performance", "Low", "AST-COMPLEXITY", node,
                     f"'{node.name}' has cyclomatic complexity {cx}.", "Break the logic into smaller parts.")
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef


# ---------- Scoring ----------
def score(findings):
    cats = {k: 100 for k in WEIGHTS}
    for f in findings:
        cats[f["category"]] = max(0, cats[f["category"]] - POINTS[f["severity"]])
    overall = sum(cats[k] * w for k, w in WEIGHTS.items())
    if any(f["severity"] == "Critical" and f["category"] == "security" for f in findings):
        overall = min(overall, 60)
    return {k: round(v) for k, v in cats.items()}, round(overall)


# ---------- Main entry ----------
def review(code):
    err = validate(code)
    if err:
        return {"error": err}
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return {"error": f"Syntax error on line {e.lineno}: {e.msg}"}

    lines, warnings = code.splitlines(), []
    checker = Checker()
    checker.visit(tree)
    findings = checker.found

    fd, path = tempfile.mkstemp(suffix=".py")  # code is written, never executed
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(code)
        for name, runner in (("Ruff", lambda: run_ruff(path, lines)),
                             ("Bandit", lambda: run_bandit(path))):
            try:
                findings += runner()
            except Exception as e:  # partial results if a tool fails
                warnings.append(f"{name} could not run ({type(e).__name__}); results are partial.")
    finally:
        os.remove(path)

    findings.sort(key=lambda f: (ORDER[f["severity"]], f["line"]))
    cats, overall = score(findings)
    return {"overall": overall, "categories": cats, "labels": LABELS,
            "findings": findings, "warnings": warnings}


def to_txt(r):
    out = ["CODE REVIEW REPORT", "=" * 40, f"Overall score: {r['overall']}/100", ""]
    out += [f"{LABELS[k]}: {v}/100" for k, v in r["categories"].items()]
    out += ["", "AUTOMATED FINDINGS", "-" * 40]
    for f in r["findings"]:
        out += [f"[{f['severity']}] {f['rule']} ({f['source']}) line {f['line']}",
                f"  {f['message']}", f"  Fix: {f['fix']}", ""]
    return "\n".join(out)
