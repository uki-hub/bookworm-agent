```
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

**Let the bookworm read your codebase, so your agent doesn't have to.**

The bookworm turns any project into clear, structured docs, so your agent already knows the plot.

![version](https://img.shields.io/badge/version-0.0.2-blue) ![status](https://img.shields.io/badge/status-beta-orange) ![license](https://img.shields.io/badge/license-MIT-green) ![python](https://img.shields.io/badge/python-3.9%2B-yellow)

## What the bookworm does

- 🗂️ **Reads once**: one doc per feature, vertical slice, with "changing X → open Y" routes
- 🛡️ **Spots changed pages**: flags docs when the code they describe changes
- ✍️ **Takes the notes**: built-in skills learn a feature (or the whole repo) into context docs
- 📏 **Keeps the rules**: plans pin the docs they used; a task is done only when checks pass and docs are refreshed
- 👥 **Shares the library**: commit `.bookworm/` to your repo and review it in PRs
- 🔒 **Keeps its paws off your code**: never commits, stages, or pushes it

## Install

```bash
/plugin marketplace add uki-hub/bookworm-agent
/plugin install bookworm@bookworm
```

Needs Claude Code ≥ 2.1.275, git, Python ≥ 3.9 (no pip packages).

## Feed it

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

<sub>Named after the childhood favorite, Bookworm Deluxe 🐛📖</sub>
