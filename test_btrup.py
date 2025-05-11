# BtrUp is a Btrfs + Borg backup script
# © 2024-2025 Toon Verstraelen
#
# This file is part of BtrUp Core.
#
# BtrUp Core is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 3
# of the License, or (at your option) any later version.
#
# BtrUp Core is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, see <http://www.gnu.org/licenses/>
#
# --
"""Unit tests for BtrUp."""

import tomllib
from datetime import datetime, timedelta

import cattrs
import pytest

from btrup import (
    Config,
    convert_interval,
    find_source,
    grandfatherson,
    parse_archives,
    parse_subvolumes,
    select_relevant,
)


@pytest.mark.parametrize(
    ("input_str", "expected"),
    [
        ("min", timedelta(minutes=1)),
        ("minute", timedelta(minutes=1)),
        ("minutes", timedelta(minutes=1)),
        ("10 min", timedelta(minutes=10)),
        ("20 minute", timedelta(minutes=20)),
        ("30 minutes", timedelta(minutes=30)),
        ("hour", timedelta(hours=1)),
        ("hours", timedelta(hours=1)),
        ("8 hour", timedelta(hours=8)),
        ("10 hours", timedelta(hours=10)),
        ("day", timedelta(days=1)),
        ("days", timedelta(days=1)),
        ("8 day", timedelta(days=8)),
        ("10 days", timedelta(days=10)),
    ],
)
def test_convert_interval(input_str, expected):
    assert convert_interval(input_str) == expected


def test_select_relevant():
    dts = [
        datetime(2022, 1, 28, 0, 0, 0),
        datetime(2022, 1, 31, 0, 0, 0),
        datetime(2022, 2, 1, 0, 0, 0),
        datetime(2022, 2, 1, 0, 0, 0),
        datetime(2022, 2, 2, 0, 0, 0),
        datetime(2022, 2, 4, 0, 0, 0),
        datetime(2022, 2, 5, 0, 0, 0),
        datetime(2022, 2, 19, 0, 0, 0),
        datetime(2022, 2, 20, 0, 0, 0),
        datetime(2022, 2, 22, 0, 0, 0),
        datetime(2022, 2, 27, 0, 0, 0),
    ]
    keep = [
        datetime(2022, 2, 1, 0, 0, 0),
        datetime(2022, 2, 4, 0, 0, 0),
        datetime(2022, 2, 19, 0, 0, 0),
        datetime(2022, 2, 22, 0, 0, 0),
        datetime(2022, 2, 27, 0, 0, 0),
    ]
    assert select_relevant(dts, datetime(2022, 1, 31, 12), timedelta(days=3), 5) == keep


def test_grandfatherson_empty():
    origin = datetime(2022, 5, 5, 0, 0, 0)
    dts = [
        datetime(2022, 5, 5, 0, 0, 0),
        datetime(2022, 5, 4, 0, 0, 0),
        datetime(2022, 5, 2, 0, 0, 0),
        datetime(2022, 5, 1, 0, 0, 0),
    ]
    assert grandfatherson(dts, origin, []) == (set(), set(dts))


def test_grandfatherson_tenminutely():
    origin = datetime(2022, 5, 5, 0, 0, 0)
    interval = timedelta(minutes=10)
    dts = [
        datetime(2022, 5, 5, 16, 35, 0),
        datetime(2022, 5, 5, 16, 45, 0),
        datetime(2022, 5, 5, 16, 55, 0),
        datetime(2022, 5, 5, 16, 57, 0),
        datetime(2022, 5, 5, 17, 21, 0),
        datetime(2022, 5, 5, 17, 25, 0),
        datetime(2022, 5, 5, 17, 32, 0),
    ]
    keep_dts = {dts[2], dts[4], dts[6]}
    prune_dts = {dts[0], dts[1], dts[3], dts[5]}
    assert grandfatherson(dts, origin, [(interval, 3)]) == (keep_dts, prune_dts)


def test_grandfatherson_hourly():
    origin = datetime(2022, 5, 5, 0, 30, 0)
    interval = timedelta(hours=1)
    dts = [
        datetime(2022, 5, 5, 15, 0, 0),
        datetime(2022, 5, 5, 16, 0, 0),
        datetime(2022, 5, 5, 16, 20, 0),
        datetime(2022, 5, 5, 17, 0, 0),
        datetime(2022, 5, 8, 0, 0, 0),
    ]
    keep_dts = {dts[1], dts[3], dts[4]}
    prune_dts = {dts[0], dts[2]}
    assert grandfatherson(dts, origin, [(interval, 3)]) == (keep_dts, prune_dts)


def test_grandfatherson_daily1():
    origin = datetime(2022, 5, 5, 3, 0, 0)
    interval = timedelta(days=1)
    dts = [
        datetime(2022, 5, 1, 0, 0, 0),
        datetime(2022, 5, 2, 0, 0, 0),
        datetime(2022, 5, 4, 0, 0, 0),
        datetime(2022, 5, 5, 0, 0, 0),
    ]
    assert grandfatherson(dts, origin, [(interval, 3)]) == (set(dts[1:]), set(dts[:1]))


def test_grandfatherson_daily2():
    origin = datetime(2022, 5, 5, 3, 0, 0)
    interval = timedelta(days=1)
    dts = [
        datetime(2022, 5, 1, 10, 0, 0),
        datetime(2022, 5, 2, 10, 0, 0),
        datetime(2022, 5, 4, 9, 0, 0),
        datetime(2022, 5, 4, 10, 0, 0),
        datetime(2022, 5, 5, 10, 0, 0),
    ]
    keep_dts = {dts[1], dts[2], dts[4]}
    prune_dts = {dts[0], dts[3]}
    assert grandfatherson(dts, origin, [(interval, 3)]) == (keep_dts, prune_dts)


def test_grandfatherson_daily_too_few():
    origin = datetime(2022, 5, 1, 3, 0, 0)
    interval = timedelta(days=2)
    dts = [
        datetime(2022, 5, 1, 0, 0, 0),
        datetime(2022, 5, 5, 0, 0, 0),
    ]
    assert grandfatherson(dts, origin, [(interval, 3)]) == (set(dts), set())


def test_grandfatherson_mixed():
    origin = datetime(2022, 5, 1, 3, 0, 0)
    interval1 = timedelta(days=1)
    interval2 = timedelta(hours=6)
    dts = [
        datetime(2022, 5, 1, 0, 0, 0),
        datetime(2022, 5, 1, 6, 0, 0),
        datetime(2022, 5, 1, 12, 0, 0),
        datetime(2022, 5, 1, 18, 0, 0),
        datetime(2022, 5, 2, 0, 0, 0),
        datetime(2022, 5, 2, 6, 0, 0),
        datetime(2022, 5, 2, 12, 0, 0),
        datetime(2022, 5, 2, 18, 0, 0),
        datetime(2022, 5, 3, 0, 0, 0),
        datetime(2022, 5, 3, 6, 0, 0),
        datetime(2022, 5, 3, 12, 0, 0),
        datetime(2022, 5, 3, 18, 0, 0),
        datetime(2022, 5, 4, 0, 0, 0),
        datetime(2022, 5, 4, 6, 0, 0),
        datetime(2022, 5, 4, 12, 0, 0),
        datetime(2022, 5, 4, 18, 0, 0),
    ]
    keep_dts = {dts[5], dts[9], dts[12], dts[13], dts[14], dts[15]}
    prune_dts = {dts[0], dts[1], dts[2], dts[3], dts[4], dts[6], dts[7], dts[8], dts[10], dts[11]}
    assert grandfatherson(dts, origin, [(interval1, 3), (interval2, 4)]) == (keep_dts, prune_dts)


EXAMPLE_MOUNTS = """
configfs /sys/kernel/config configfs rw,nosuid,nodev,noexec,relatime 0 0
/dev/sda3 /home btrfs rw,noatime,ssd,discard=async,space_cache=v2,subvolid=256,subvol=/home 0 0
/dev/sda3 / btrfs rw,noatime,ssd,discard=async,space_cache=v2,subvolid=258,subvol=/root 0 0
tmpfs /run/wrappers tmpfs rw,nodev,relatime,size=16388940k,mode=755 0 0
"""


def test_find_source_root():
    dev, volume = find_source(EXAMPLE_MOUNTS, "/")
    assert dev == "/dev/sda3"
    assert volume == "/root"


def test_find_source_home():
    dev, volume = find_source(EXAMPLE_MOUNTS, "/home")
    assert dev == "/dev/sda3"
    assert volume == "/home"


def test_find_source_home_foo():
    dev, volume = find_source(EXAMPLE_MOUNTS, "/home/foo")
    assert dev == "/dev/sda3"
    assert volume == "/home"


EXAMPLE_VOLUMES1 = """
ID 256 gen 219417 top level 5 path home
ID 333 gen 205386 top level 5 path snapshots/home.2025_02_17__03_00_48
ID 334 gen 208196 top level 5 path snapshots/home.2025_02_18__03_00_42
ID 335 gen 211006 top level 5 path snapshots/home.2025_02_19__03_00_46
ID 336 gen 213816 top level 5 path snapshots/home.2025_02_20__03_00_46
ID 337 gen 216626 top level 5 path snapshots/home.2025_02_21__03_00_46
"""


def test_parse_subvolumes1():
    volumes = parse_subvolumes(EXAMPLE_VOLUMES1, "snapshots/home.", "%Y_%m_%d__%H_%M_%S")
    assert volumes == {
        datetime(2025, 2, 17, 3, 0, 48): "snapshots/home.2025_02_17__03_00_48",
        datetime(2025, 2, 18, 3, 0, 42): "snapshots/home.2025_02_18__03_00_42",
        datetime(2025, 2, 19, 3, 0, 46): "snapshots/home.2025_02_19__03_00_46",
        datetime(2025, 2, 20, 3, 0, 46): "snapshots/home.2025_02_20__03_00_46",
        datetime(2025, 2, 21, 3, 0, 46): "snapshots/home.2025_02_21__03_00_46",
    }


EXAMPLE_VOLUMES2 = """
ID 256 gen 219417 top level 5 path home
ID 333 gen 205386 top level 5 path snapshots/home.2025_02_17__03_00_48
ID 333 gen 205386 top level 5 path snapshots/home.foo
"""


def test_parse_subvolumes2():
    with pytest.raises(ValueError):
        parse_subvolumes(EXAMPLE_VOLUMES2, "snapshots/home.", "%Y_%m_%d__%H_%M_%S")


EXAMPLE_ARCHIVES = """
home.2025_02_18__03_00_42            Tue, 2025-02-18 04:00:42 [2d06]
home.2025_02_19__03_00_46            Wed, 2025-02-19 04:00:46 [47c5]
home.2025_02_20__03_00_46            Thu, 2025-02-20 04:00:46 [5521]
home.2025_02_21__03_00_46            Fri, 2025-02-21 04:00:46 [3d81]
home.2025_02_22__03_02_29            Sat, 2025-02-22 04:02:29 [f7f6]
"""


def test_parse_archives1():
    archives = parse_archives(EXAMPLE_ARCHIVES, "home.", "%Y_%m_%d__%H_%M_%S")
    assert archives == {
        datetime(2025, 2, 18, 3, 0, 42): "home.2025_02_18__03_00_42",
        datetime(2025, 2, 19, 3, 0, 46): "home.2025_02_19__03_00_46",
        datetime(2025, 2, 20, 3, 0, 46): "home.2025_02_20__03_00_46",
        datetime(2025, 2, 21, 3, 0, 46): "home.2025_02_21__03_00_46",
        datetime(2025, 2, 22, 3, 2, 29): "home.2025_02_22__03_02_29",
    }


def test_parse_archives2():
    with pytest.raises(ValueError):
        parse_archives(EXAMPLE_ARCHIVES, "data.", "%Y_%m_%d__%H_%M_%S")


EXAMPLE_CONFIG1 = """
datetime_format = '%Y_%m_%d__%H_%M'
time_origin = '2024_05_01__07_15'

[[keeps]]
interval = "10 minutes"
amount = 12

[[keeps]]
interval = "hour"
amount = 48

[[keeps]]
backup = true
interval = "day"
amount = 28

[[keeps]]
backup = true
interval = "7 days"
amount = 52

[btrfs]
source_path = "/home"
prefix = "snapshots/home."
snapshot_mnt = "/mnt"
pre = []
post = []

[borg]
prefix = "home."
env = {}
extra = []
paths = ["alice", "bob"]
repositories = ["/mnt/bigdisk", "offsite:/mnt/storage"]
"""


def test_load_config1():
    data = tomllib.loads(EXAMPLE_CONFIG1)
    print(data)
    config = cattrs.structure(data, Config)
    assert config.datetime_format == "%Y_%m_%d__%H_%M"
    assert config.time_origin == datetime(2024, 5, 1, 7, 15)
    assert config.btrfs.source_path == "/home"
    assert config.btrfs.prefix == "snapshots/home."
    assert config.btrfs.snapshot_mnt == "/mnt"
    assert config.borg.prefix == "home."
    assert config.borg.paths == ["alice", "bob"]
    assert config.borg.repositories == ["/mnt/bigdisk", "offsite:/mnt/storage"]
    assert len(config.keeps) == 4
    assert config.keeps[0].interval == timedelta(minutes=10)
    assert config.keeps[0].amount == 12
    assert config.keeps[0].backup is False
    assert config.keeps[-1].interval == timedelta(days=7)
    assert config.keeps[-1].amount == 52
    assert config.keeps[-1].backup is True


EXAMPLE_CONFIG2 = """
[[keeps]]
interval = "hour"
amount = 48

[btrfs]
source_path = "/"
prefix = "snapshots/foo."
snapshot_mnt = "/data"
"""


def test_config2():
    data = tomllib.loads(EXAMPLE_CONFIG2)
    config = cattrs.structure(data, Config)
    assert config.datetime_format == "%Y_%m_%d__%H_%M_%S"
    assert config.time_origin == datetime(2024, 1, 1, 3, 55, 0)
    assert config.btrfs.source_path == "/"
    assert config.btrfs.prefix == "snapshots/foo."
    assert config.btrfs.snapshot_mnt == "/data"
    assert config.borg.prefix == "backup."
    assert config.borg.paths == []
    assert config.borg.repositories == []
    assert len(config.keeps) == 1
    assert config.keeps[0].interval == timedelta(hours=1)
    assert config.keeps[0].amount == 48
    assert config.keeps[0].backup is False
