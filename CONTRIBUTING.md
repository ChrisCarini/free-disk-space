# Contributing

Include the problem, reasoning, and relevant trade-offs with each change. A small fix may need only a sentence;
a behavior change should explain alternatives, confidence in the choice, and evidence that would change the decision.
Credit the people who reported or diagnosed the issue.

This follows the upstream [contribution policy](https://github.com/jlumbroso/free-disk-space/blob/36e9a5af4eddb91fc11aec4c6f6f79b3cc0cb523/CONTRIBUTING.md).
Its [design records](https://github.com/jlumbroso/free-disk-space/tree/36e9a5af4eddb91fc11aec4c6f6f79b3cc0cb523/docs/adr)
document the shared boundaries and original reasoning. Link the relevant record when proposing a change to those boundaries.

## Scope and defaults

The action frees space by deleting preinstalled software, not by repartitioning disks or restructuring the runner.
New options should include a measured saving on a named Ubuntu runner image.

Aggressive defaults are appropriate when a user can trace a failure to the removed software. Default to `false` when removal
can cause a fundamental resource failure with no visible connection to this action. This is why swap and preinstalled
runtimes are opt-in. Describe how a user who needed the removed resource would discover its absence.

Specific subject options take precedence over general categories. A new subject option must explicitly exempt its software
from applicable category removals and include regression tests; this is not automatic.

## Python and observability

Keep cleanup in `free_disk_space.py` rather than adding a second implementation in shell.
Pass inputs through the action's environment and commands as argument lists, never interpolated shell code.
Use the existing `recording` and `run_command` helpers for per-option measurements and command error reporting.
Retain existing Sentry operation names when renaming an input, and expose the configured inputs and any exemptions in telemetry.

When changing inputs, update `action.yml`, Python configuration, README examples/defaults, and both workflows together.
The hourly matrix covers every canonical boolean combination; aliases belong in separate compatibility tests.
Changing the input set also changes runner usage, so call out the resulting matrix size.

## Testing

Use an isolated environment and run:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

Tests must stub cleanup commands and keep Sentry events in memory. Never run the cleanup script on your development machine.

CI runs on pull-request updates, pushes to `main`, and manual dispatches. Feature-branch pushes do not trigger CI on
their own, avoiding duplicate runs for open pull requests.

The workflows exercise the checked-out action on disposable GitHub-hosted Ubuntu runners. Include a workflow run link
when proposing behavior changes, and report any local or hosted-runner limitations.
