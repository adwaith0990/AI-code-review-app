from reviewer import review, score, validate


def test_empty_input():
    assert validate("   ")


def test_syntax_error():
    assert "Syntax error" in review("def f(:")["error"]


def test_bare_except_and_mutable_default():
    code = 'def f(x=[]):\n    """d"""\n    try:\n        pass\n    except:\n        pass\n'
    rules = {f["rule"] for f in review(code)["findings"]}
    assert {"AST-BARE-EXCEPT", "AST-MUTABLE-DEFAULT", "AST-EXCEPT-PASS"} <= rules


def test_critical_security_caps_score():
    f = [{"category": "security", "severity": "Critical"}]
    assert score(f)[1] <= 60


def test_clean_code_scores_high():
    r = review('def add(a, b):\n    """Add."""\n    return a + b\n')
    assert r["overall"] >= 95
