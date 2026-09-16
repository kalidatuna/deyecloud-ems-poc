# Contributing

Start by reading the README and reproducing the behavior you want to change. Keep changes focused and describe the user-visible result.

## Local validation

Run from the repository root:

```sh
python3 -m unittest discover -v
```

Use the injected `post` and `get` transports for deterministic tests. Preserve dry-run defaults and explicit control-write gating. Do not add live cloud or inverter calls to CI. Cover pagination boundaries and error paths when changing discovery. Never commit credentials, real device identifiers, or unreviewed account reports.

## Submitting changes

1. Create a branch for the change.
2. Add regression coverage for behavior changes and update relevant examples.
3. Run the checks above and `git diff --check`.
4. Open a pull request describing the problem, change, test results, and any remaining limitations.

For bug reports, include runtime versions, a minimal reproduction, expected and actual behavior, and sanitized output. Do not include tokens or credentials. Keep hardware-dependent observations separate from offline results.

## Continuous integration

CI runs the offline suite on every push and pull request with read-only repository permissions. Action versions are pinned to commit IDs. The matrix covers Python 3.10 and 3.12. No third-party dependencies, secrets, or live service access are required.
