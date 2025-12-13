<!-- markdownlint-disable no-duplicate-heading -->

# Changelog

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Effort-based Versioning](https://jacobtomlinson.dev/effver/).
(Changes to features documented as "experimental" will not increment macro and meso version numbers.)

## [Unreleased]

Bug fixes and security improvements.

### Changed

- Renamed config key `btrfs.snapshot_mnt` to `btrfs.root_mnt`
  to better reflect its purpose as the mount point of the Btrfs root volume.
  This means that config files must be updated accordingly.

### Fixed

- Fix typos.
- Hardcode paths to `btrfs` and `borg` binaries for security reasons.
- Fix and document `sudoers` configuration to allow mounting and unmounting
  Btrfs subvolumes when using Borg backup functionality.
- Minor robustness improvements.

## [1.0.2] - 2025-06-30

### Fixed

Fix bug triggered when Borg is not configured.

## [1.0.1] - 2025-06-29

### Fixed

This is a minor bugfix release, mainly addressing redundant borg calls.

## [1.0.0] - 2025-05-11

This is the first versioned release of BtrUp, previously distributed as "backup-script".
This release switches to the GPLv3 license.
The code itself has undergone various improvements to facilitate configuration and improve security.
It can now run as a non-root user with a limited configuration of `sudoers`.

### Changes

- BtrUp is distributed under the conditions of the GPLv3 license.
- Installable through PyPI.
- Replaced YAML by TOML config file.
- Validate TOML config with [attrs](https://www.attrs.org/en/stable/) and
  [cattrs](https://catt.rs/en/stable/) before doing anything else.
- Add "sudo" to btrfs commands to allow running them from a non-root account.
- Call sudo with absolute path to btrfs for security reasons.
- Facilitate and generalize configuration of btrfs snapshots.
- Improved snapshot and backup retention configuration and algorithm.
- More unit tests
- More documentation

[Unreleased]: https://github.com/reproducible-reporting/btrup
[1.0.2]: https://github.com/reproducible-reporting/btrup/releases/tag/v1.0.2
[1.0.1]: https://github.com/reproducible-reporting/btrup/releases/tag/v1.0.1
[1.0.0]: https://github.com/reproducible-reporting/btrup/releases/tag/v1.0.0
