<div align="center">

```text
  _______
 /       \  _______
/ -O--O-  \/        \
|      __  |   __   |
 \_____/   |_   |   |
    |  ><   |   |\__\
    |           |
    \__________/
```

# Bookworm

**Project memory for Claude Code that knows when it's out of date.**

![version](https://img.shields.io/badge/version-0.0.2-blue) ![status](https://img.shields.io/badge/status-beta-orange) ![license](https://img.shields.io/badge/license-MIT-green) ![python](https://img.shields.io/badge/python-3.9%2B-yellow)

</div>

## What it does

- 📚 **Learns** your codebase into source-backed docs, one per feature
- 🔍 **Detects drift** when code changes under the docs
- 📝 **Plans** work pinned to the docs it was based on
- ✅ **Gates** every task: done only when checks pass and docs are refreshed
- 🔒 **Safe**: never commits, stages, or pushes your code

## Install

```bash
/plugin marketplace add uki-hub/bookworm-agent
/plugin install bookworm@bookworm
```

Needs Claude Code ≥ 2.1.275, git, Python ≥ 3.9 (no pip packages).

## Use

```text
/bookworm:init                      set up .bookworm/
/bookworm:learn checkout flow       learn one feature
/bookworm:learn-all                 map the whole repo
/bookworm:context-check --all       find stale docs
/bookworm:do fix cart rounding; acceptance: npm test passes
```

## Docs

[Guide](docs/GUIDE.md) · [Use cases](docs/USE-CASES.md) · [Benchmarks](docs/BENCHMARKS.md) · [Changelog](docs/CHANGELOG.md) · [Plugin reference](bookworm/README.md)

## License

[MIT](LICENSE)
