# Objective
Remove the hardcoded default Lit API key (`GK4rv4T/...`) from source code so it's not shipped to GitHub. Then connect to GitHub and push the repo.

# Tasks

### T001: Remove hardcoded Lit API key
- **Blocked By**: []
- **Details**:
  - Remove `os.environ.setdefault("LIT_API_KEY", "GK4rv4T/...")` from `gui.py` (line 54) and `web_app.py` (line 24)
  - Update `web_app.py` `api_settings_load` — remove the `default_lit` comparison; instead just check if `LIT_API_KEY` is set at all
  - The app should work fine without a default key — users create their own via the "Create Free API Key" button, or paste one in Settings
  - Files: `gui.py`, `web_app.py`
  - Acceptance: No hardcoded API keys in any source file; `grep -r "GK4rv4T" .` returns nothing

### T002: Connect GitHub and push
- **Blocked By**: [T001]
- **Details**:
  - Set up the GitHub integration via Replit's connector
  - User completes OAuth to connect their GitHub account
  - Push the repo to GitHub
  - Acceptance: Code is on GitHub with no hardcoded secrets
