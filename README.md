# Free Disk Space on Ubuntu runners

A customizable GitHub Action to free disk space on Linux GitHub Actions runners.

This is a fork of [jlumbroso/free-disk-space](https://github.com/jlumbroso/free-disk-space), with the notable changes being:

* Script ported to Python
* Sentry.io support _(via setting a `SENTRY_DSN` repository secret of your [Sentry DSN](https://docs.sentry.io/concepts/key-terms/dsn-explainer/))_

## Motivation

The main motivation for this fork was being able to identify which particular flag(s) take the most/least amount of time.
While this action can clear ~31GB (according to the original `README.md`), an execution might not need that much additional
space cleared. When choosing a subset of options to set, it can be helpful to know both (a) how much space might be cleared,
and (b) how much time it will take to clear said space.

## TODO

At some point, I'd love to have a dynamically generated table show on this `README.md` that visually gives folks an idea of
which option(s) they can use to clear the most amount of space (according to their needs) in the least amount of time.
