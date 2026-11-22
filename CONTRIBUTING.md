# Contributing to data-whisperer

Thank you for your interest in contributing! This document provides guidelines for contributing to the project.

## Code of Conduct

This project adheres to a [Code of Conduct](CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code.

## How to Contribute

### Reporting Bugs

Before creating a bug report, please check the [issue tracker](https://github.com/yourusername/data-whisperer/issues) to see if the issue has already been reported.

When creating a bug report, include:
- **Clear title** describing the issue
- **Steps to reproduce** the problem
- **Expected behavior** vs **actual behavior**
- **Environment details** (OS, Python version, Docker version)
- **Logs/error messages** (if applicable)
- **Screenshots** (if UI-related)

### Suggesting Enhancements

Enhancement suggestions are welcome! Please provide:
- **Use case** - Why is this needed?
- **Proposed solution** - How should it work?
- **Alternatives considered** - What else did you consider?
- **Additional context** - Any other relevant information

### Pull Request Process

1. **Fork** the repository and create your branch from `main`
2. **Write tests** for any new functionality
3. **Update documentation** for any changed behavior
4. **Ensure all checks pass** (lint, type-check, tests)
5. **Submit a PR** with a clear description

## Development Setup

### Prerequisites
- Python 3.11+
- Docker & Docker Compose
- Git

### Local Development

```bash
# Clone your fork
git clone https://github.com/YOUR_USERNAME/data-whisperer.git
cd data-whisperer

# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install in development mode
pip install --upgrade pip
pip install -e .[dev,test]

# Start infrastructure
docker compose up -d postgres redis jaeger

# Run API locally (for development)
uvicorn data_platform.api.main:app --reload --port 8000

# Run workers in separate terminals
python -m data_platform.workers.ingestor
python -m data_platform.workers.etl
python -m data_platform.workers.analysis
python -m data_platform.workers.merge
python -m data_platform.workers.sql_agent
python -m data_platform.workers.python_agent
python -m data_platform.workers.viz_agent
python -m data_platform.workers.insight_agent
```

### Pre-commit Hooks

Install pre-commit hooks for automatic formatting:

```bash
pip install pre-commit
pre-commit install
```

This will run Ruff formatting and linting on every commit.

## Coding Standards

### Python Style

- **Formatter**: Ruff (compatible with Black)
- **Linter**: Ruff (replaces flake8, isort, etc.)
- **Type Checking**: MyPy (strict mode)
- **Line Length**: 100 characters
- **Quotes**: Double quotes for strings

### Type Hints

- All public functions must have type hints
- Use `TypedDict` for dictionary shapes
- Prefer `list[str]` over `List[str]` (Python 3.9+)
- Use `|` for unions (Python 3.10+)

### Documentation

- **Docstrings**: Google style for all public classes/functions
- **Comments**: Explain *why*, not *what*
- **README**: Update for user-facing changes
- **Architecture**: Update ARCHITECTURE.md for structural changes

### Testing

- **Unit Tests**: Test individual functions/classes in isolation
- **Integration Tests**: Test component interactions (require Docker)
- **E2E Tests**: Test full pipeline flows
- **Coverage Target**: >80% for new code

```bash
# Run all tests
pytest tests/ -v --cov=data_platform

# Run specific test file
pytest tests/test_agents.py -v

# Run with coverage report
pytest tests/ --cov=data_platform --cov-report=html
```

## Architecture Guidelines

### Adding New Connectors

1. Subclass `BaseConnector` in `data_platform/connectors/`
2. Implement `fetch()` (async generator) and `validate_config()`
3. Register via entry_point in `pyproject.toml`
4. Add tests in `tests/connectors/`

### Adding New Agents

1. Subclass `BaseLLMAgent` in `data_platform/agents/`
2. Define `name`, `system_prompt`, `tools`
3. Implement `run()` returning `AgentOutput`
4. Register via entry_point in `pyproject.toml`
5. Add worker in `data_platform/workers/`
6. Add stream consumer group config

### Database Changes

1. Modify models in `data_platform/models/__init__.py`
2. Create migration script (or update `init.sql` for fresh installs)
3. Update schemas in `data_platform/schemas/__init__.py`
4. Test with `docker compose up -d postgres` + `python -c "from data_platform.core.database import init_db; import asyncio; asyncio.run(init_db())"`

## Commit Message Convention

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>[optional scope]: <description>

[optional body]

[optional footer(s)]
```

Types:
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation only
- `style`: Formatting, no code change
- `refactor`: Code restructure, no behavior change
- `perf`: Performance improvement
- `test`: Adding/modifying tests
- `chore`: Maintenance, deps, build

Examples:
```
feat(agents): add sentiment analysis agent
fix(orchestrator): handle checkpoint corruption gracefully
docs(api): update authentication examples
refactor(core): simplify rate limiter implementation
```

## Release Process

Releases are automated via GitHub Actions on merge to `main`:

1. Version bump (via `pyproject.toml` or semantic-release)
2. Changelog generation
3. Docker image build & push to GHCR
4. GitHub Release creation

## Getting Help

- **Discord**: [Community Server](https://discord.gg/example)
- **Discussions**: [GitHub Discussions](https://github.com/yourusername/agentic-data-platform/discussions)
- **Email**: maintainer@example.com

## Recognition

Contributors will be recognized in:
- `CONTRIBUTORS.md` file
- Release notes
- Project README (for significant contributions)

Thank you for contributing! 🚀