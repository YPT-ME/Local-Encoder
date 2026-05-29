# Contributing to Local Encoder

Thanks for your interest in contributing!

## Getting started

```bash
git clone https://github.com/YPT-ME/Local-Encoder
cd Local-Encoder

python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

pip install -e ".[dev]"
```

## Running the checks

```bash
pytest                  # run tests
ruff check .            # lint
ruff format .           # format
mypy local_encoder      # type-check
```

All four must pass before opening a pull request.

## Pull request guidelines

- Keep PRs focused — one feature or fix per PR.
- Add or update tests for any code you change.
- Update `README.md` if you change user-facing behaviour.
- Use [Conventional Commits](https://www.conventionalcommits.org/) for commit messages
  (`feat:`, `fix:`, `refactor:`, `docs:`, `chore:`).

## Reporting bugs

Open an issue and include:
- Python version (`python --version`)
- FFmpeg version (`ffmpeg -version`)
- The full error message / traceback
- Steps to reproduce

## License

By contributing you agree your changes will be released under the [MIT License](LICENSE).
