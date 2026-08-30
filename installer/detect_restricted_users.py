#!/usr/bin/python3
"""Detect interactive non-administrator Ubuntu accounts for the installer."""

from __future__ import annotations

import argparse
import grp
import pwd
import re
from dataclasses import dataclass
from pathlib import Path


ADMIN_GROUPS = {"sudo", "admin"}
DISABLED_SHELLS = {"/bin/false", "/usr/bin/false", "/sbin/nologin", "/usr/sbin/nologin"}


@dataclass(frozen=True)
class Account:
    name: str
    uid: int
    gid: int
    shell: str


@dataclass(frozen=True)
class Group:
    name: str
    gid: int
    members: tuple[str, ...]


def uid_bounds(path: Path) -> tuple[int, int]:
    minimum = 1000
    maximum = 60000
    if not path.is_file():
        return minimum, maximum
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        match = re.fullmatch(r"(UID_MIN|UID_MAX)\s+(\d+)", line)
        if not match:
            continue
        if match.group(1) == "UID_MIN":
            minimum = int(match.group(2))
        else:
            maximum = int(match.group(2))
    if minimum <= 0 or maximum < minimum:
        raise ValueError("UID_MIN/UID_MAX in login.defs sind ungültig")
    return minimum, maximum


def file_accounts(path: Path) -> list[Account]:
    accounts: list[Account] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = line.split(":")
        if len(fields) != 7:
            raise ValueError(f"ungültiger passwd-Eintrag: {line!r}")
        accounts.append(Account(fields[0], int(fields[2]), int(fields[3]), fields[6]))
    return accounts


def file_groups(path: Path) -> list[Group]:
    groups: list[Group] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = line.split(":")
        if len(fields) != 4:
            raise ValueError(f"ungültiger group-Eintrag: {line!r}")
        members = tuple(member for member in fields[3].split(",") if member)
        groups.append(Group(fields[0], int(fields[2]), members))
    return groups


def system_accounts() -> list[Account]:
    return [Account(item.pw_name, item.pw_uid, item.pw_gid, item.pw_shell) for item in pwd.getpwall()]


def system_groups() -> list[Group]:
    return [Group(item.gr_name, item.gr_gid, tuple(item.gr_mem)) for item in grp.getgrall()]


def detect(
    accounts: list[Account],
    groups: list[Group],
    uid_min: int,
    uid_max: int,
    excluded_uids: set[int],
) -> list[Account]:
    administrator_names: set[str] = set()
    administrator_gids: set[int] = set()
    for group in groups:
        if group.name in ADMIN_GROUPS:
            administrator_gids.add(group.gid)
            administrator_names.update(group.members)
    return sorted(
        (
            account
            for account in accounts
            if uid_min <= account.uid <= uid_max
            and account.uid not in excluded_uids
            and account.name not in administrator_names
            and account.gid not in administrator_gids
            and account.shell not in DISABLED_SHELLS
            and bool(account.shell)
        ),
        key=lambda account: account.uid,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("/"))
    parser.add_argument("--exclude-uid", type=int, action="append", default=[])
    args = parser.parse_args()

    login_defs = args.root / "etc/login.defs"
    uid_min, uid_max = uid_bounds(login_defs)
    if args.root == Path("/"):
        accounts = system_accounts()
        groups = system_groups()
    else:
        passwd_path = args.root / "etc/passwd"
        group_path = args.root / "etc/group"
        if not passwd_path.is_file() or not group_path.is_file():
            raise SystemExit("Test-Root benötigt etc/passwd und etc/group für die Benutzererkennung")
        accounts = file_accounts(passwd_path)
        groups = file_groups(group_path)

    detected = detect(accounts, groups, uid_min, uid_max, set(args.exclude_uid) | {0})
    for account in detected:
        print(f"{account.uid}:{account.name}")


if __name__ == "__main__":
    main()
