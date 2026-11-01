# Free Disk Space on Ubuntu runners

A customizable GitHub Action to free disk space on Linux GitHub Actions runners.

This is a fork of [jlumbroso/free-disk-space](https://github.com/jlumbroso/free-disk-space), with the notable changes being:

* Script ported to Python
* Sentry.io support _(by passing your [Sentry DSN](https://docs.sentry.io/concepts/key-terms/dsn-explainer/) as the `SENTRY_DSN` environment variable; a repository secret is recommended)_

## Motivation

The main motivation for this fork was being able to identify which particular flag(s) take the most/least amount of time.
While this action can clear ~31GB (according to the original `README.md`), an execution might not need that much additional
space cleared. When choosing a subset of options to set, it can be helpful to know both (a) how much space might be cleared,
and (b) how much time it will take to clear said space.

## Usage

```yaml
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Free Disk Space
        uses: ChrisCarini/free-disk-space@main
        env:
          SENTRY_DSN: ${{ secrets.SENTRY_DSN }}
        with:
          android: true
          dotnet: true
          haskell: true
          large-packages: true
          docker-images: true
          preinstalled-runtimes: false
          swap-storage: false
```

All inputs are optional. Without a DSN, cleanup and disk-space reporting still work; Sentry reporting is disabled.
This action deletes software on the runner. Use it on disposable Ubuntu runners, not a development machine.

## Upgrading existing workflows

These changes follow upstream's v1-to-v2 migration; the examples use this fork's `@main`, not an assumed release tag.

- Rename `tool-cache` to `preinstalled-runtimes`. The old input continues to work until v3.0.0.
- Add `swap-storage: true` only if you want swap removed. It is now preserved by default to avoid hard-to-diagnose
  memory-pressure failures, reported by @zaikunzhang in [jlumbroso/free-disk-space#12](https://github.com/jlumbroso/free-disk-space/issues/12).
- `dotnet: false` now also protects .NET from the large-package sweep. The overlap was reported by @gmij in
  [jlumbroso/free-disk-space#6](https://github.com/jlumbroso/free-disk-space/issues/6), reported again by @ashleney in
  [jlumbroso/free-disk-space#33](https://github.com/jlumbroso/free-disk-space/issues/33), and diagnosed there by @ax3l.

## Sentry instrumentation

Cleanup retains its transaction, per-option and per-package timing spans, command error capture, and freed-space measurements.
Transactions include the GitHub repository, workflow, run, and job tags, plus `input.<input-name>` tags for all eight inputs.
`cleanup.preinstalled_runtimes` records the effective value after resolving the two runtime inputs.

The runtime-cleanup span retains its existing `cleanup.toolcache` operation so existing dashboards keep working.
Its description uses the new name, and `deprecated_alias_used` records whether `tool-cache` was enabled.
If `AGENT_TOOLSDIRECTORY` is missing or empty, cleanup is skipped with a warning and `skipped: true` on the span.

## Testing and upstream provenance

The hourly workflow runs all **128 distinct cleanup configurations** across the seven canonical inputs, including
Docker cleanup and runtime cleanup both enabled and disabled. The deprecated alias is held at `false` in that matrix;
the four alias combinations are covered separately by regression tests. Workflows check out and run the current revision.

The local tests replace every cleanup command and use an in-memory Sentry transport: they neither delete runner software
nor send events to Sentry.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

This Python port incorporates the nine upstream commits through
[`36e9a5a`](https://github.com/jlumbroso/free-disk-space/commit/36e9a5af4eddb91fc11aec4c6f6f79b3cc0cb523).
The input-indirection fix by @nbuckwalt in
[jlumbroso/free-disk-space#51](https://github.com/jlumbroso/free-disk-space/pull/51) is preserved: inputs are passed via
environment variables, never interpolated into shell commands. This fork keeps its Python/Sentry implementation;
upstream's [design records and evidence](https://github.com/jlumbroso/free-disk-space/tree/36e9a5af4eddb91fc11aec4c6f6f79b3cc0cb523/docs/adr)
remain the source for the historical rationale. See [CONTRIBUTING.md](CONTRIBUTING.md) for the adapted contribution policy.

## TODO

At some point, I'd love to have a dynamically generated table show on this `README.md` that visually gives folks an idea of
which option(s) they can use to clear the most amount of space (according to their needs) in the least amount of time.
