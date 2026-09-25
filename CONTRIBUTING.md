# Contributing Guide

## Development Setup

### Prerequisites
- Python 3.7+ with pip
- Node.js 14+ (for CLI form testing)
- Git Bash or equivalent (Windows)
- Aliyun SLS account with read access to production logs
- `@bty/customer-service-cli` installed and authenticated

### Initial Setup

```bash
# Clone and enter repository
cd <克隆目录>/cs-cli

# Install Python dependencies
pip install -r requirements.txt

# Configure data sources
cp scripts/channels.example.json scripts/channels.json
# Edit scripts/channels.json with real SLS AK

# Configure leak detection (for build)
cp scripts/leak_patterns.example.json scripts/leak_patterns.json
# Edit scripts/leak_patterns.json with your personal patterns (username, partial AK prefix, etc.)

# Verify authentication
python scripts/server_log_query.py --check
python scripts/rpa_log_query.py --check
python scripts/ops_log_query.py --check
```

## Running Tests

```bash
# Run full test suite
python -m pytest tests/ -v

# Run specific test file
python -m pytest tests/test_timezone.py -v

# Run with coverage (optional)
pip install pytest-cov
python -m pytest tests/ --cov=scripts --cov-report=html
```

**All tests must pass before committing changes.**

## Code Style

### Python
- Follow PEP 8
- UTF-8 encoding with BOM handling: `'utf-8-sig'` for file reads
- Use type hints for function signatures
- Beijing time (UTC+8) for all timestamps: `CST = timezone(timedelta(hours=8))`

### Exception Handling
Use the two-tier pattern from `scripts/exceptions.py`:

```python
from exceptions import DataSourceError, categorize_sls_error

errors_collected = []

try:
    result = query_sls(...)
except DataSourceError as e:
    print(f"❌ Query failed: {e} (source={e.source}, recoverable={e.recoverable})")
    errors_collected.append(e)
except Exception as e:
    err = categorize_sls_error(e, "source-name")
    print(f"❌ Query failed: {err} (source={err.source}, recoverable={err.recoverable})")
    errors_collected.append(err)
```

### Timezone Handling
Always use timezone-aware datetimes:

```python
from datetime import datetime, timedelta, timezone

CST = timezone(timedelta(hours=8))

# Parse user input (naive → Beijing time)
def _parse_input_dt(s: str) -> datetime:
    dt = datetime.fromisoformat(s)
    return dt if dt.tzinfo else dt.replace(tzinfo=CST)

# Format Unix timestamp for display
time_str = datetime.fromtimestamp(ts, tz=CST).strftime('%Y-%m-%d %H:%M:%S')
```

## Building & Packaging

### Before Building
1. **Commit your changes**: Both build scripts warn on uncommitted changes
2. **Update version** if releasing: `cli/package.json`, skill versions
3. **Run tests**: `python -m pytest tests/`

### Build Commands

```bash
# Build npm CLI form (.tgz)
powershell -ExecutionPolicy Bypass -File build_cli.ps1

# Build zip distribution form
powershell -ExecutionPolicy Bypass -File build_package.ps1

# Skip zip compression (faster iteration)
powershell -ExecutionPolicy Bypass -File build_package.ps1 -SkipZip

# Strict mode (fail on uncommitted changes)
powershell -ExecutionPolicy Bypass -File build_cli.ps1 -Strict
```

### Quality Gates
Both build scripts run:
1. **Syntax check**: `python -m py_compile` on all .py files
2. **JSON validation**: Parse all .json templates
3. **Leak detection**: Scan for personal paths/AK patterns from `scripts/leak_patterns.json`
4. **Cleanup**: Remove `__pycache__` directories

**Never commit** these files:
- `scripts/channels.json` (contains SLS AK)
- `scripts/leak_patterns.json` (contains personal patterns)
- `temp/*` (analysis output)
- `dist/*` (build artifacts)

All are in `.gitignore`.

## Testing Locally

### CLI Form
```bash
# Build and install locally
powershell -File build_cli.ps1
npm install -g dist/cs-debug-toolkit-<ver>.tgz

# Initialize
csdbg init

# Configure (copy SLS AK)
# Edit ~/.csdbg/channels.json

# Test
csdbg cross --query "test" --start "2024-09-23T12:00:00" --end "2024-09-23T12:05:00" --limit 5
```

### Zip Form
```bash
# Build
powershell -File build_package.ps1

# Unpack to test location
unzip dist/cs-debug-toolkit.zip -d /tmp/test-install

# Setup
cd /tmp/test-install
powershell -File setup.ps1

# Test
python scripts/cross_analysis.py --query "test" --start "2024-09-23T12:00:00" --end "2024-09-23T12:05:00" --limit 5
```

## Adding New Features

### New Data Source
1. Create `scripts/<source>_query.py` with query logic
2. Add exception handling using two-tier pattern
3. Use timezone-aware datetime operations
4. Add tests in `tests/test_<source>_query.py`
5. Update `cross_analysis.py` to integrate the source
6. Document in README.md

### New Skill
1. Create `skill/<skill-name>/` directory
2. Write `SKILL.md` with complete instructions
3. Add entry in `.claude/commands/<skill-name>.md` if needed
4. Update README.md skill table
5. Test via agent before committing

### Modifying Exception Handling
1. Add new exception subclass in `scripts/exceptions.py` if needed
2. Update `categorize_sls_error()` or `categorize_cli_error()` patterns
3. Add test cases in `tests/test_exceptions.py`
4. Update error rendering in affected query scripts

## Debugging Tips

### Query Scripts
```bash
# Enable verbose output (most scripts support --quiet, omit it for debug)
python scripts/server_log_query.py --conversation-id <id> --start <iso> --end <iso>

# Check authentication
python scripts/server_log_query.py --check
python scripts/rpa_log_query.py --check
python scripts/ops_log_query.py --check

# Inspect raw output
python scripts/cross_analysis.py ... 
# Check temp/evidence_<timestamp>_<slug>/ for raw JSON
```

### Test Isolation
- Tests use fake Aliyun SDK (see `tests/conftest.py`)
- Test output goes to `tests/.test_temp/` (isolated from real `temp/`)
- To test against real SLS, write integration tests separately

### Common Issues
- **"泄漏嫌疑" build failure**: Your personal pattern in `leak_patterns.json` matched a distributed file (usually `.example.json`). Use non-overlapping placeholders in `.example` files.
- **Timezone test failures**: Verify `CST` constant is `timezone(timedelta(hours=8))` in all modules
- **Import errors in tests**: Check `tests/conftest.py` injects fake SDK before imports

## Release Checklist

Before releasing a new version:

- [ ] All tests pass (`python -m pytest tests/`)
- [ ] Version bumped in `cli/package.json`
- [ ] CHANGELOG.md updated with changes
- [ ] Both builds succeed without warnings
- [ ] Leak detection gate passes (no personal data in artifacts)
- [ ] Test installation of both forms (npm + zip)
- [ ] Skills load correctly in target agent environment
- [ ] Update documentation if API/CLI changed

## Architecture Overview

```
Four data sources → cross_analysis.py → evidence.md
                                      ↓
                    LLM (via /cs-log-cross skill) → temp/analysis_*.md
```

### Key Design Principles
1. **Single source**: All distribution forms built from this repository
2. **Dual form**: npm CLI (recommended) + zip (offline/no-npm environments)
3. **Tool-agnostic**: Scripts output JSON/markdown; LLM consumes via skills
4. **Evidence-based**: Raw logs + cross-analysis both preserved in `temp/`
5. **Four-source completeness**: Server + RPA + Ops + Host/IP for full picture

### Critical Files
- **`scripts/cross_analysis.py`**: Core four-source orchestration
- **`scripts/exceptions.py`**: Exception hierarchy (don't bypass it)
- **`build_cli.ps1` / `build_package.ps1`**: Quality gates + packaging
- **`skill/cs-log-cross/SKILL.md`**: Main LLM entry point for analysis
- **`tests/conftest.py`**: Test infrastructure (fake SDK, isolation)

## Getting Help

- Check existing `temp/` directories for analysis examples
- Review memory files in `.claude/memories/` for project context
- Consult PRDs in `docs/` for feature requirements
- Examine skill SKILL.md files for usage patterns

## License

Internal use only — BetterYeah DevKit
