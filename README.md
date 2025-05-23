# BtrUp: Btrfs + Borg backup script

:warning: **Warning** :warning:
You use BtrUp at your own risk.
You are the only person responsible for any damage caused by the use of BtrUp.
:warning:

BtrUp is distributed under the terms of the GPLv3 license.
See the [LICENSE](LICENSE) file for more details.

See [CHANGELOG.md](CHANGELOG.md) for the version history.

## Installation

```bash
pip install btrup
```

You must also have a [Btrfs filesystem](https://btrfs.readthedocs.io/en/latest/)
and [Borg Backup](https://www.borgbackup.org/) installed on your computer.

## Usage

BtrUp is executed on the command line with a TOML config file as mandatory argument.

```bash
btrup CONFIG [-n] [-s]
```

The option `-n` will result in a dry run and can be used to test the configuration.

The option `-s` skips the creation of a new snapshot,
which can be useful after a successful snapshot followed by a failed or interrupted Borg backup.

The config file has the following format:

```toml
# Datetime format used for snapshot and backup suffixes.
datetime_format = '%Y_%m_%d__%H_%M_%S'
# Time origin to discretize time into bins.
time_origin = '2024_01_01__03_55_00'

# To determine which snapshots and backups to keep,
# time is divided into bins of equal width
# Each [[keeps]] section specifies the bin width as "interval".
# The first bin starts at time_origin in every [[keeps]] section.
# Within one bin, only the oldest snapshot (and backup) is retained.
# When there are multiple [[keeps]] sections,
# a spanshot is kept if it matches the criteria of
# at least one of the [[keeps]] sections.

# With the `time_origin` in this example,
# the daily backup corresponds to the snapshot made at 4am

# The 12 most recent 10-minutely snapshots are retained, not backed up.
[[keeps]]
interval = "10 minutes"
amount = 12

# The 28 most recent hourly snapshot are retained, not backed up.
[[keeps]]
interval = "hour"
amount = 48

# The 14 most recent daily snapshot are retained and backed up.
[[keeps]]
backup = true
interval = "day"
amount = 14

# The 52 most recent weekly snapshot are retained and backed up.
[[keeps]]
backup = true
interval = "7 days"
amount = 52

[btrfs]
# Mount point of the Btrfs volume to take snapshot from, must be mounted.
source_path = "/home"
# Prefix for btrfs snapshot volumes, timestamp is appended.
prefix = "snapshots/home."
# Path where the snapshot volumes will be mounted.
snapshot_mnt = "/mnt"
# The snapshot path will be "{snapshot_mnt}/{prefix}{datetime}".
# The snapshots must be stored in the same Btrfs file system as the source.
# In this example, `/mn/snapshots` must be a Btrfs volume
# in the same filesystem as that of the `/home` volume,

# Commands to be executed before making a snapshot: cleanups, mysqldump, etc.
pre = []
# Commands to be executed after making a snapshot: remove dump etc.
post = []
# Note that each command is a string that is executed without a subshell.

[borg]
# Prefix used for Borg archives
prefix = "home."
# List of borg repositories
repositories = ["/mnt/bigdisk", "offsite:/mnt/storage"]
# The archive name is "{repository}::{prefix}{datetime}" for each repository.

# Dictionary with environment variables set for each Borg command, e.g. BORG_CACHE_DIR
env = {}
# Extra arguments for borg create command, e.g. to define exclusions
extra = []
# Paths inside the subvolume to backup.
paths = ["alice", "bob"]

# If you prefer to disable the borg backup, delete the entire borg section
# or leave the list of repositories empty.
```

Ideally, backups are performed by a dedicated user account with access to user data and backups.
Users, whose data is being backed up, should only have read access to the backups.
This way, they (or any malware running in their account) cannot damage the backed up data.

## Periodic backups

To run BtrUp on a regular basis,
you can write a shell script that calls BtrUp with the desired arguments,
and then add this shell script to the crontab of the backup account.

A more modern solution is to create a systemd timer and service.
The instructions below should be executed **as root**.

Start by creating a `backup` user that will run the backup process:

```bash
useradd backup -s /sbin/nologin
```

Install `btrup` systemwide, as some Linux distributions (using SELinux)
will not allow services to execute programs located in home directories.

```bash
pip install btrup
```

Create two files in `/etc/systemd/system/`:

`/etc/systemd/system/btrup.timer`:

```ini
[Unit]
Description=Periodic backup with BtrUp

[Timer]
# Every hour. See man systemd.timer(5)
OnCalendar=hourly
Persistent=true
Unit=btrup.service

[Install]
WantedBy=default.target
```

`/etc/systemd/system/btrup.service`

```ini
[Unit]
Description=Periodic backup with BtrUp

[Service]
Type=oneshot
User=backup
ExecStart=/usr/local/bin/btrup /etc/btrup/config.toml
AmbientCapabilities=CAP_DAC_READ_SEARCH
```

You also need to create a configuration file `/etc/btrup/config.toml`.
(This can be generalized towards multiple configs and a shell script calling `btrup` for each config.)
For security reasons, it is recommended to use absolute paths for all executables,
which may be different on your system.

The flag `CAP_DAC_READ_SEARCH` gives the backup service account global read-access.
In addition, you need to configure `sudoers` to allow the backup user to manage Btrfs subvolumes.
This can be accomplished with the following lines in your
[`sudoers`](https://www.man7.org/linux/man-pages/man5/sudoers.5.html) configuration:

```text
backup ALL=(ALL) NOPASSWD: /usr/sbin/btrfs subvolume snapshot -r /home *
backup ALL=(ALL) NOPASSWD: /usr/sbin/btrfs subvolume list /home
backup ALL=(ALL) NOPASSWD: /usr/sbin/btrfs subvolume delete /mnt/snapshots/home.*
```

Make sure you make these commands match your config file and are specific as possible.
By making them more specific, you will reduce the risk of accidental wrong subvolume operations.
Also ensure that you use `visudo` to edit the `sudoers` file,
to avoid that mistakes in your `sudoers` file will lock you out of the root account.

To enable the backup timer and service, run the following as root:

```bash
systemctl daemon-reload
systemctl enable --now btrup.timer
```

To check the state of the timer:

```bash
systemctl list-timers
```

To test the backup without waiting for the timer

```bash
systemctl start btrup.service
```

To check the backup logs:

```bash
journalctl -efu btrup.service
```

## Credits

BtrUp is written by Toon Verstraelen.
Most of the magic in BtrUp is provided by two great tools:

- BtrUp assume your data resides in a [Btrfs](https://docs.kernel.org/filesystems/btrfs.html)
  file system volume, which is used by BtrUp to create snapshots.
- Backups of the snapshots are made with [Borg](https://www.borgbackup.org/).
