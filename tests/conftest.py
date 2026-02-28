from pathlib import Path

# Prevent pytest from collecting test files inside smoke test example apps.
# These are third-party repos with their own test suites and dependencies
# that are not installed in harden's test environment.
_examples = Path(__file__).parent / "smoke" / "examples"
collect_ignore = [str(p) for p in _examples.iterdir() if p.is_dir()] if _examples.exists() else []
