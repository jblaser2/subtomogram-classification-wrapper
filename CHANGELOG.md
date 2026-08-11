# Changelog

All notable changes to this project are documented here.

## [Unreleased]

### Added
- Initial repo scaffolding: `src/stw` package layout, core abstractions
  (`spec`, `config`, `requirements`, `capabilities`), mask primitives (sphere + cylinder),
  generic class-averaging, cross-package comparison, the `Adapter` contract, and a first
  Tier-A adapter (HAC Baseline).
- CLI: `stw list`, `stw check-env`, `stw init`, `stw run`.
- CI: unit tests + adapter contract tests on every push.
