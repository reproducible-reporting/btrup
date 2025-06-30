#!/usr/bin/env python3
# BtrUp is a Btrfs + Borg backup script
# © 2024-2025 Toon Verstraelen
#
# This file is part of BtrUp.
#
# BtrUp is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 3
# of the License, or (at your option) any later version.
#
# BtrUp is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, see <http://www.gnu.org/licenses/>
#
# --
"""Backup with btrfs snapshots and multiple borg repositories.

See https://github.com/reproducible-reporting/btrup for more information.
"""

import argparse
import logging
import os
import shlex
import shutil
import subprocess
import sys
import tomllib
from datetime import datetime, timedelta
from time import sleep

import attrs
import cattrs

LOGGER = logging.getLogger(__name__)


def select_relevant(
    available: list[datetime], origin: datetime, interval: timedelta, amount: int
) -> list[datetime]:
    """Determine which from the available datetimes are relevant.

    The time axis is divided into bins of width `step` starting from `origin`.
    All available datetimes are then mapped into bins.
    Only datetimes from the count most recent bins are kept.
    If there are multiple datetimes within one bin, the oldest datetime is kept.

    Parameters
    ----------
    available
        A list of datetime objects.
    origin
        The origin of the time axis used to discretize time into bins.
    interval
        The width of the bins on the time axis.
    amount
        The number of relevant datetimes to keep.

    Returns
    -------
    relevant
        The relevant datetimes.
    """
    bins = {}
    for dt in available:
        bin_idx = (dt - origin) // interval
        bins.setdefault(bin_idx, dt)
        bins[bin_idx] = min(bins[bin_idx], dt)
    bins = sorted(bins.values())
    return bins[-amount:]


def grandfatherson(
    available: list[datetime],
    origin: datetime,
    keeps: list[tuple[timedelta, int]],
) -> tuple[set[datetime], set[datetime]]:
    """Use the GFS algorithm to determine which datetimes should be kept and which should be pruned.

    Parameters
    ----------
    available
        A list of datetime objects.
    origin
        The origin of the time axis used to discretize time into bins.
    keeps
        A list of tuples, each containing an interval and an amount of datetimes to keep.

    Returns
    -------
    keep_dts
        The datetimes to be kept.
    prune_dts
        The datetimes to be pruned.
    """
    keep_dts = set()
    for interval, amount in keeps:
        keep_dts.update(select_relevant(available, origin, interval, amount))
    prune_dts = set(available) - keep_dts
    return keep_dts, prune_dts


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(prog="btrup", description="Backup with btrfs and borg")
    parser.add_argument("config", help="TOML config file")
    parser.add_argument(
        "-n",
        "--dry-run",
        default=False,
        action="store_true",
        help="Skip actual Btrfs and Borg commands, except when getting info from them.",
    )
    parser.add_argument(
        "-s",
        "--skip-snapshot",
        default=False,
        action="store_true",
        help="Do not make a new snapshot. Only run Borg.",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        default=False,
        action="store_true",
        help="Only show output of Btrfs and Borg commands.",
    )
    return parser.parse_args(argv)


def convert_interval(value: str | timedelta) -> timedelta:
    if isinstance(value, timedelta):
        return value
    words = value.split()
    if len(words) == 1:
        number = 1
        unit = words[0]
    elif len(words) == 2:
        number = int(words[0])
        unit = words[1]
    else:
        raise ValueError(f"Invalid interval: {value}. More than two words")
    if unit in ("min", "minute", "minutes"):
        return timedelta(minutes=number)
    if unit in ("hour", "hours"):
        return timedelta(hours=number)
    if unit in ("day", "days"):
        return timedelta(days=number)
    raise ValueError(f"Invalid unit: {unit}")


@attrs.define
class KeepConfig:
    interval: timedelta = attrs.field(converter=convert_interval)
    """Interval of the snapshots to keep."""

    amount: int = attrs.field()
    """Amount of snapshots (and backups) to keep."""

    backup: bool = attrs.field(default=False)
    """Whether to backup the snapshot with Borg as well."""


@attrs.define
class BtrfsConfig:
    source_path: str = attrs.field()
    """Path of the mounted Btrfs volume to take snapshots from."""

    device: str = attrs.field(init=False, default="")
    """Device of the Btrfs volume."""

    source_volume: str = attrs.field(init=False, default="")
    """Btrfs volume corresponding to the source path."""

    prefix: str = attrs.field()
    """Prefix for the snapshot subvolumes, timestamp is appended."""

    snapshot_mnt: str = attrs.field()
    """Path where the snapshot subvolumes will be mounted."""

    pre: list[str] = attrs.field(factory=list, converter=list)
    """Commands to run before creating a snapshot."""

    post: list[str] = attrs.field(factory=list, converter=list)
    """Commands to run after creating a snapshot."""


def find_source(mounts: str, path: str) -> tuple[str, str]:
    """Get the device and volume of a mounted path from the contents of /proc/mounts."""
    best = None
    for line in mounts.split("\n"):
        words = line.split()
        if len(words) < 4 or words[2] != "btrfs":
            continue
        if path.startswith(words[1]) and (best is None or len(words[1]) > len(best[1])):
            best = words
    if best is not None:
        for item in best[3].split(","):
            if item.startswith("subvol="):
                return best[0], item[7:]
        raise ValueError(f"Could not find subvol= in {best[3]}")
    raise FileNotFoundError(f"Could not find {path} in /proc/mounts")


@attrs.define
class BorgConfig:
    prefix: str = attrs.field(default="backup.")
    """Prefix for the Borg archives."""

    env: dict[str, str] = attrs.field(factory=dict, converter=dict)
    """Environment variables to set before running Borg commands."""

    repositories: list[str] = attrs.field(factory=list, converter=list)
    """List of Borg repositories to archive to."""

    paths: list[str] = attrs.field(factory=list, converter=list)
    """List of paths to archive."""

    extra: list[str] = attrs.field(factory=list, converter=list)
    """Extra arguments for all borg commands in list form."""


def convert_time_origin(value: str | datetime, obj: attrs.AttrsInstance) -> datetime:
    if isinstance(value, datetime):
        return value
    if not isinstance(obj, Config):
        raise TypeError(f"Expected Config instance, got {type(obj)}")
    return datetime.strptime(value, obj.datetime_format)


@attrs.define
class Config:
    keeps: list[KeepConfig] = attrs.field()
    """List of intervals and amounts of snapshots to keep."""

    btrfs: BtrfsConfig = attrs.field()
    """Btrfs configuration, used for snapshots."""

    borg: BorgConfig = attrs.field(factory=BorgConfig)
    """Borg configuration, used for backups."""

    datetime_format: str = attrs.field(default="%Y_%m_%d__%H_%M_%S")
    """Format of the datetime suffixes in the snapshot subvolumes."""

    time_origin: datetime = attrs.field(
        default=datetime(2024, 1, 1, 3, 55, 0),
        converter=attrs.Converter(convert_time_origin, takes_self=True),
    )
    """Origin of the time axis used to discretize time into bins."""


def main(argv: list[str] | None = None):
    """Main program."""
    args = parse_args(argv)

    # Set log level
    logging.basicConfig(
        format="%(asctime)s : %(message)s",
        level=logging.WARNING if args.quiet else logging.INFO,
    )

    # Load TOML config file
    with open(args.config, "rb") as fh:
        config = cattrs.structure(tomllib.load(fh), Config)

    # Work on the Btrfs part
    snapshots = main_btrfs(config, args)

    if len(snapshots) > 0:
        # Work on the Borg part
        main_borg(config, args, snapshots)


def main_btrfs(config: Config, args: argparse.Namespace) -> dict[datetime, str]:
    """Main Btrfs part of the program."""
    # Find device and volume
    with open("/proc/mounts") as fh:
        config.btrfs.device, config.btrfs.source_volume = find_source(
            fh.read(), config.btrfs.source_path
        )

    # Get existing snapshot
    output = run(["sudo", get_brfs(), "subvolume", "list", config.btrfs.source_path], capture=True)
    snapshots = parse_subvolumes(output, config.btrfs.prefix, config.datetime_format)

    # Determine if a snapshot already exists in the current keep intervals.
    if not args.skip_snapshot:
        # The new timestamp is re-derived from the subvolume name for consistency.
        new_subvol = config.btrfs.prefix + datetime.now().strftime(config.datetime_format)
        new_dt = parse_suffix(new_subvol, config.btrfs.prefix, config.datetime_format)
        snapshots[new_dt] = new_subvol
        keep_dts, prune_dts = grandfatherson(
            list(snapshots),
            config.time_origin,
            [(keep.interval, keep.amount) for keep in config.keeps],
        )
        if new_dt in keep_dts:
            create_btrfs_snapshot(config, new_subvol, args.dry_run)
        else:
            del snapshots[new_dt]
            prune_dts.discard(new_dt)
        prune_old_btrfs_snapshots(config, prune_dts, snapshots, args.dry_run)
    return snapshots


def get_brfs():
    """Get the fully qualified path to Btrfs."""
    # For security reasons we don't want to use `sudo` with `PATH`.
    btrfs = shutil.which("btrfs")
    if btrfs is None:
        raise FileNotFoundError("Could not find 'btrfs' in PATH")
    return btrfs


def create_btrfs_snapshot(config: Config, new_subvol: str, dry_run: bool):
    """Create a new Btrfs snapshot."""
    try:
        LOGGER.info("Preparing for snapshot")
        for command in config.btrfs.pre:
            run(shlex.split(command), dry_run)

        LOGGER.info("Making a new snapshot")
        run(
            [
                "sudo",
                get_brfs(),
                "subvolume",
                "snapshot",
                "-r",
                config.btrfs.source_path,
                os.path.join(config.btrfs.snapshot_mnt, new_subvol),
            ],
            dry_run,
        )
    finally:
        LOGGER.info("Cleaning after snapshot")
        for command in config.btrfs.post:
            run(shlex.split(command), dry_run)


def prune_old_btrfs_snapshots(
    config: Config, prune_dts: set[datetime], snapshots: dict[datetime, str], dry_run: bool
):
    """Delete old Btrfs snapshots using the GFS algorithm."""
    LOGGER.info("Pruning old snapshots")
    # Execute sub-volume deletion commands.
    for dt in sorted(prune_dts):
        snapshot_path = os.path.join(config.btrfs.snapshot_mnt, snapshots[dt])
        run(["sudo", get_brfs(), "subvolume", "delete", snapshot_path], dry_run)
        del snapshots[dt]


def parse_subvolumes(output: str, prefix: str, datetime_format: str) -> dict[datetime, str]:
    """Parse the output of `btrfs subvolume list` and select relevant snapshot volumes."""
    snapshots = {}
    for line in output.split("\n"):
        words = line.split()
        if len(words) == 0:
            continue
        subvol = words[-1]
        if not subvol.startswith(prefix):
            continue
        dt = parse_suffix(subvol, prefix, datetime_format)
        snapshots[dt] = subvol
    return snapshots


def main_borg(config: Config, args: argparse.Namespace, snapshots: dict[datetime, str]):
    """Main Borg part of the program."""
    # Get the list of snapshots to keep for borg backup
    dts_keep = grandfatherson(
        list(snapshots),
        config.time_origin,
        [(keep.interval, keep.amount) for keep in config.keeps if keep.backup],
    )[0]

    # Check if there is anything to keep.
    if len(dts_keep) == 0:
        LOGGER.info("No snapshots selected for backup, skipping Borg.")
        return

    # If the latest snapshot is not in the keep list, do not run Borg.
    last_snapshot = max(snapshots)
    if max(snapshots) not in dts_keep:
        LOGGER.info(f"Skipping borg, snapshot not selected for backup: ({last_snapshot})")
        LOGGER.info(f"Most recent snapshot selected for backup: {max(dts_keep)}")
        return

    # Filter snapshots, only those in keep list. (prune list is not complete.)
    snapshots = {dt: subvol for dt, subvol in snapshots.items() if dt in dts_keep}

    # Backup the selected snapshots to every Borg repository.
    env = config.borg.env
    for repository in config.borg.repositories:
        if not check_borg_repository(repository, env):
            LOGGER.info("Could not access %s", repository)
            continue
        archives = get_borg_archives(config, repository, env)

        LOGGER.info("Creating new borg archives (%s)", repository)
        for dt, subvol in snapshots.items():
            if dt in archives:
                continue
            create_borg_archive(config, args.dry_run, repository, env, subvol)

        LOGGER.info("Pruning old archives if any (%s)", repository)
        removed = prune_old_borg_archives(args.dry_run, repository, env, snapshots, archives)
        if removed:
            compact_borg_repository(args.dry_run, repository, env)


def check_borg_repository(repository: str, env: dict[str, str]) -> bool:
    """Get basic info from a borg repository."""
    try:
        run(["borg", "info", repository], env=os.environ | env)
    except subprocess.CalledProcessError:
        return False
    return True


def get_borg_archives(config: Config, repository: str, env: dict[str, str]) -> dict[datetime, str]:
    """Get a list of archives in the Borg repository."""
    LOGGER.info("Getting a list of borg archives (%s)", repository)
    prefix = config.borg.prefix
    output = run(["borg", "list", repository], env=(os.environ | env), capture=True)
    return parse_archives(output, prefix, config.datetime_format)


def parse_archives(output: str, prefix: str, datetime_format: str) -> dict[datetime, str]:
    """Parse the output of `borg list` and select relevant archives."""
    archives = {}
    for line in output.split("\n"):
        words = line.strip().split()
        if len(words) == 0:
            continue
        archive = words[0]
        if not archive.startswith(prefix):
            raise ValueError(f"Archive '{archive}' has the wrong prefix. Should be '{prefix}'")
        dt = parse_suffix(archive, prefix, datetime_format)
        archives[dt] = archive
    return archives


def create_borg_archive(
    config: Config, dry_run: bool, repository: str, env: dict[str, str], subvol: str
):
    """Create a Borg backup from a Btrfs snapshot."""
    dn_current = os.path.join(config.btrfs.snapshot_mnt, config.btrfs.prefix + "current")
    if os.path.isdir(dn_current):
        run(["umount", dn_current], dry_run, check=False)
    else:
        LOGGER.info("Creating directory %s", dn_current)
        os.makedirs(dn_current)

    run(["mount", config.btrfs.device, dn_current, "-o", f"subvol={subvol},noatime"], dry_run)

    paths = config.borg.paths
    if not dry_run:
        for path in paths:
            full_path = os.path.join(dn_current, path)
            if not os.path.exists(full_path):
                raise ValueError(f"Path does not exist: {full_path}")

    try:
        dt = parse_suffix(subvol, config.btrfs.prefix, config.datetime_format)
        suffix = dt.strftime(config.datetime_format)
        timestamp = dt.isoformat()
        run(
            [
                "borg",
                "create",
                "--verbose",
                "--stats",
                "--show-rc",
                "--timestamp",
                timestamp,
                *config.borg.extra,
                f"{repository}::{config.borg.prefix}{suffix}",
                *paths,
            ],
            dry_run,
            env=(os.environ | env),
            cwd=dn_current,
        )
    finally:
        # It may take some time before the disk is no longer considered "in use".
        sleep(1.0)
        run(["umount", dn_current], dry_run)
        LOGGER.info("Removing %s", dn_current)
        os.rmdir(dn_current)


def prune_old_borg_archives(
    dry_run: bool,
    repository: str,
    env: dict[str, str],
    snapshots: dict[datetime, str],
    archives: dict[datetime, str],
) -> bool:
    """Delete old Bort archives using the GFS algorithm."""
    LOGGER.info("Removing old borg archives (%s)", repository)
    removed = False
    for dt, archive in sorted(archives.items()):
        if dt not in snapshots:
            removed = True
            run(
                [
                    "borg",
                    "delete",
                    f"{repository}::{archive}",
                ],
                dry_run,
                env=(os.environ | env),
            )
    return removed


def compact_borg_repository(dry_run: bool, repository: str, env: dict[str, str]):
    """Reduce the space occupied by the Borg archive by removing unused data."""
    LOGGER.info("Compacting repository after removing old archives (%s)", repository)
    run(
        [
            "borg",
            "compact",
            repository,
        ],
        dry_run,
        env=(os.environ | env),
    )


def parse_suffix(name: str, prefix: str, datetime_format: str) -> datetime:
    """Extract the datetime object from the name of an archive."""
    if not name.startswith(prefix):
        raise ValueError(f"Name '{name}' should start with '{prefix}'")
    return datetime.strptime(name[len(prefix) :], datetime_format)


def run(cmd: list[str], dry_run: bool = False, capture: bool = False, **kwargs) -> str:
    """Print and run a command."""
    cmd_info = " ".join(cmd)
    if "cwd" in kwargs:
        cmd_info = f"{cmd_info}  # in {kwargs['cwd']}"
    if dry_run:
        LOGGER.info("Skipping %s", cmd_info)
        return ""
    LOGGER.info("Running %s", cmd_info)
    # Make sure output is written in correct order.
    sys.stdout.flush()

    if "stdin" not in kwargs:
        kwargs["stdin"] = subprocess.DEVNULL
    if "encoding" not in kwargs:
        kwargs["encoding"] = "utf-8"
        kwargs["universal_newlines"] = True
    if capture:
        kwargs["capture_output"] = True
    cp = subprocess.run(cmd, **kwargs)  # noqa: PLW1510
    return cp.stdout or ""


if __name__ == "__main__":
    main(sys.argv[1:])
