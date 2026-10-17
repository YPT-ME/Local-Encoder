# Contributing

[Source setup and architecture](docs/development.md) · [Open an issue](https://github.com/YPT-ME/Local-Encoder/issues)

## Pull requests

1. Keep each PR focused on one feature or fix.
2. Add or update tests for code changes.
3. Update the [user guide](docs/user-guide.md) for user-facing changes, the README for basics,
   and [encoder parity](docs/encoder-parity.md) when integration behavior changes.
4. Run all four checks:

   ```bash
   pytest
   ruff check .
   ruff format --check .
   mypy local_encoder
   ```

Encoding, login and upload changes also need a real AVideo integration test.
Use [Conventional Commits](https://www.conventionalcommits.org/) such as `feat:`, `fix:` or `docs:`.

## Bug reports

Include the app version, operating system, steps to reproduce and the error shown.
Use **Report a problem** in the app to attach logs. Never include passwords or access tokens.
For source installations, also include Python and FFmpeg versions.

## License

Contributions are released under the [MIT License](LICENSE).
