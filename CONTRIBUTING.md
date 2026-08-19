# Contributing to Koode TaskGraph

Thank you for taking the time to contribute. This guide explains how to send
changes to Koode TaskGraph using a fork-based pull request workflow.

## Language

All project communication must be in English. This includes issues, pull
requests, commit messages, code comments, documentation, examples, and user
visible text.

## Code Standards

Koode TaskGraph is a Python project. Contributions should follow:

- PEP 8 for Python style.
- Clear, descriptive names for classes, functions, variables, nodes, ports, and
  properties.
- Type hints for new public functions, methods, and data structures where they
  improve readability.
- Small, focused changes. Avoid unrelated refactors in feature or bug-fix pull
  requests.
- Standard-library solutions unless a new dependency is clearly justified.
- QtPy imports for Qt code, not direct PySide6 imports, unless there is no QtPy
  abstraction available.

Keep comments useful and concise. Prefer code that explains itself through
structure and naming.

## Development Setup

Create and use a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

On Windows:

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install -e .
```

Run the GUI:

```bash
koode-taskgraph
```

Run the headless CLI:

```bash
koode-taskgraph-cli --file path/to/graph.taskgraph
```

## Running Tests

Tests use Python's built-in `unittest` module. Do not add pytest-only test
features unless the project intentionally reintroduces pytest.

Run the full test suite:

```bash
python -m unittest discover -s tests -v
```

Also check package dependencies:

```bash
python -m pip check
```

For syntax/import validation:

```bash
python -m compileall -q taskgraph tests examples
```

## Fork and Pull Request Workflow

1. Fork the repository to your own GitHub account.
2. Clone your fork locally.
3. Create a branch from the latest main branch.
4. Make your changes.
5. Run the tests and checks listed above.
6. Push your branch to your fork.
7. Open a pull request from your fork branch into the upstream repository.

Example:

```bash
git clone https://github.com/YOUR_USERNAME/REPO_NAME.git
cd REPO_NAME
git remote add upstream https://github.com/UPSTREAM_OWNER/REPO_NAME.git
git fetch upstream
git checkout -b my-change upstream/main
```

Before opening a pull request, sync with upstream if needed:

```bash
git fetch upstream
git rebase upstream/main
```

Use a clear branch name, for example:

```text
fix-cli-error-message
add-file-property-editor
docs-custom-node-example
```

## Pull Request Expectations

A good pull request should include:

- A clear description of what changed and why.
- Screenshots or short screen recordings for visible UI changes.
- Tests for new behavior or bug fixes.
- Documentation updates when user-facing behavior changes.
- No generated cache files, virtualenv files, build artifacts, or local graph
  files.

Generated files such as `dist/`, `build/`, `*.egg-info/`, `__pycache__/`,
`.pytest_cache/`, and `.venv/` should not be committed.

## Custom Nodes and Plugins

When adding built-in nodes or examples:

- Keep node behavior deterministic.
- Put heavy work in `process()`, not `__init__()`.
- Keep dependency ports separate from attribute/value ports.
- Return output values as a dictionary whose keys match declared output ports.
- Use GUI plugins only for UI behavior. Do not require GUI plugins for headless
  CLI execution.

Custom node examples should be small and easy to understand. GUI plugin
examples should avoid external services unless they are optional and clearly
documented.

## Dependency Policy

New runtime dependencies should be rare. If a dependency is necessary, explain
why it is needed in the pull request.

Do not install packages globally for development. Use the project virtual
environment only.

## Commit Messages

Write commit messages in English. Keep them short and specific:

```text
Add file property editor
Fix disabled node execution state
Document GUI plugin loading
```

Avoid vague messages such as:

```text
updates
fix stuff
changes
```

## Commit Hygiene

Do not submit pull requests with a large number of junk or work-in-progress
commits. Before opening a pull request, squash or reorganize commits into
logical groups.

Good commit grouping:

```text
Add GUI plugin loader
Document plugin API
Add plugin loader tests
```

Poor commit grouping:

```text
wip
fix
fix again
testing
final
final 2
```

Each commit should represent a coherent change that a maintainer can review on
its own. If several tiny commits are only useful as your local working history,
squash them before submitting the pull request.

## Review Process

Maintainers may ask for changes before merging. Keep follow-up commits focused
on the requested review feedback. If the pull request changes direction
significantly, update the description so reviewers can evaluate the final
intent clearly.
