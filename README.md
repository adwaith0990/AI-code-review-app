# AI Code Review App 
Reviews Python code with Ruff, Bandit and AST checks, scores it 0-100, and exports JSON/TXT reports.

## Run
    python -m venv .venv
    .venv\Scripts\activate        # Windows  (macOS/Linux: source .venv/bin/activate)
    pip install -r requirements.txt
    python app.py                 # open http://127.0.0.1:5000
    pytest                        # run tests
