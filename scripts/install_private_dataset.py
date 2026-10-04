"""Install only the Dam worker's five local data files from an owner-supplied ZIP.

Run on the Dam worker device. Only analytical fields are written to a separate
runtime folder; the source archive and development files are preserved. Archive
code, documents and evaluation files are never extracted or executed.
"""

import argparse
import json
import os
from pathlib import Path
import stat
import tempfile
import zipfile

from backend.shared.dam_records import DATA_FILES, project_record
from backend.shared.dam_snapshots import iter_snapshots, snapshot_days


ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_PREFIX = "toddbrook_dataset/data/"
MAX_ARCHIVE_BYTES = 32 * 1024 * 1024
MAX_MEMBER_BYTES = 4 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_ENTRIES = 512
MAX_LINE_BYTES = 65536
MAX_ROWS = 10000
MAX_SNAPSHOT_BYTES = 128 * 1024 * 1024


class InstallError(ValueError):
    """A fixed local diagnostic that does not disclose record contents."""


def _reject():
    raise InstallError("The archive does not satisfy the bounded dataset format.")


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _reject()
        result[key] = value
    return result


def _prepare_records(filename, data):
    rows, prepared = 0, []
    for line in data.decode("utf-8").splitlines():
        if not line.strip():
            continue
        rows += 1
        if len(line.encode("utf-8")) > MAX_LINE_BYTES or rows > MAX_ROWS:
            _reject()
        # Parse the bounded container, then inspect only the analytical fields.
        # Discarded metadata never enters the canonical runtime files.
        row = json.loads(line, object_pairs_hook=_pairs)
        selected = project_record(filename, row)
        prepared.append(json.dumps(selected, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n")
    canonical = "".join(prepared).encode("utf-8")
    if len(canonical) > MAX_MEMBER_BYTES:
        _reject()
    return canonical


def _archive_files(archive):
    """Check every entry, but read only the exact five allowlisted data members."""
    archive = Path(archive).expanduser()
    if archive.is_symlink() or not archive.is_file() or archive.stat().st_size > MAX_ARCHIVE_BYTES:
        _reject()
    selected, seen, total = {}, set(), 0
    with archive.open("rb") as source, zipfile.ZipFile(source) as package:
        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode) or os.fstat(source.fileno()).st_size > MAX_ARCHIVE_BYTES:
            _reject()
        entries = package.infolist()
        if len(entries) > MAX_ENTRIES:
            _reject()
        for info in entries:
            name = info.orig_filename
            parts = name.rstrip("/").split("/")
            mode = stat.S_IFMT(info.external_attr >> 16)
            if (name != info.filename or name in seen or not name or name.startswith("/")
                    or "\\" in name or ":" in name or any(ord(c) < 32 for c in name)
                    or any(part in {"", ".", ".."} for part in parts)
                    or mode not in {0, stat.S_IFREG, stat.S_IFDIR}
                    or info.flag_bits & 1
                    or info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
                    or info.file_size > MAX_MEMBER_BYTES or info.file_size < 0):
                _reject()
            seen.add(name)
            total += info.file_size
            if total > MAX_TOTAL_BYTES:
                _reject()
            basename = name.removeprefix(ARCHIVE_PREFIX)
            if name.startswith(ARCHIVE_PREFIX) and basename in DATA_FILES:
                if info.is_dir() or mode == stat.S_IFDIR:
                    _reject()
                with package.open(info) as member:
                    data = member.read(MAX_MEMBER_BYTES + 1)
                if len(data) > MAX_MEMBER_BYTES or len(data) != info.file_size:
                    _reject()
                selected[basename] = _prepare_records(basename, data)
    if set(selected) != DATA_FILES:
        _reject()
    return selected


def _directory(path):
    if path.is_symlink():
        raise InstallError("The private dataset destination must not use symbolic links.")
    if path.exists():
        if not path.is_dir():
            raise InstallError("The private dataset destination must be a directory.")
    else:
        path.mkdir(mode=0o700)


def _existing_directory(path):
    if path.is_symlink():
        raise InstallError("The private dataset destination must not use symbolic links.")
    if path.exists() and not path.is_dir():
        raise InstallError("The private dataset destination must be a directory.")
    return path.exists()


def _check_files(destination, files):
    for name, data in files.items():
        path = destination / name
        matches = False
        if not path.is_symlink() and path.is_file() and path.stat().st_size == len(data):
            with path.open("rb") as stream:
                matches = stream.read(MAX_MEMBER_BYTES + 1) == data
        if not matches:
            raise InstallError("Existing private data differs or is incomplete. Preserve and inspect it locally; nothing was replaced.")


def _write_files(destination, files):
    destination.mkdir(mode=0o700)
    for name, data in files.items():
        with (destination / name).open("xb") as stream:
            os.chmod(destination / name, 0o600)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())


def install_dataset(archive, *, repo_root=ROOT):
    """Prepare exact-date inputs offline and atomically publish new directories."""
    try:
        files = _archive_files(archive)
        root = Path(repo_root).resolve(strict=True)
        private = root / "private_data"
        package = private / "toddbrook_runtime"
        destination, snapshots = package / "data", package / "as_of"
        _directory(private)
        _directory(package)
        lock = package / ".install.lock"
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            raise InstallError("Another install may be active. Inspect the local install lock before retrying.") from None
        os.close(descriptor)
        try:
            existing_data = _existing_directory(destination)
            existing_snapshots = _existing_directory(snapshots)
            if existing_data:
                _check_files(destination, files)
            with tempfile.TemporaryDirectory(prefix=".install-", dir=package) as staging:
                staged = Path(staging)
                if not existing_data:
                    _write_files(staged / "data", files)
                if not existing_snapshots:
                    (staged / "as_of").mkdir(mode=0o700)
                total = 0
                for as_of, prepared in iter_snapshots(files, dates=snapshot_days()):
                    total += sum(len(data) for data in prepared.values())
                    if total > MAX_SNAPSHOT_BYTES:
                        raise InstallError("Prepared historical inputs exceed the bounded installation size.")
                    if existing_snapshots:
                        day = snapshots / as_of.isoformat()
                        if not _existing_directory(day) or not _existing_directory(day / "data"):
                            raise InstallError("Existing private data differs or is incomplete. Preserve and inspect it locally; nothing was replaced.")
                        _check_files(day / "data", prepared)
                    else:
                        day = staged / "as_of" / as_of.isoformat()
                        day.mkdir(mode=0o700)
                        _write_files(day / "data", prepared)
                # All preparation and comparisons finish before publishing either
                # directory. Existing source/runtime directories are preserved.
                for target, source, existing in ((destination, staged / "data", existing_data),
                                                  (snapshots, staged / "as_of", existing_snapshots)):
                    if existing:
                        continue
                    if target.exists() or target.is_symlink():
                        raise InstallError("The destination changed during installation; nothing was replaced.")
                    os.rename(source, target)
            return "unchanged" if existing_data and existing_snapshots else "installed"
        finally:
            lock.unlink()
    except InstallError:
        raise
    except (OSError, ValueError, TypeError, UnicodeError, RuntimeError, RecursionError,
            OverflowError, zipfile.BadZipFile, zipfile.LargeZipFile):
        raise InstallError("Dataset installation failed. Check the archive and local filesystem; no archive code was run.") from None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("archive", type=Path, help="Owner-supplied ZIP on this Dam worker device.")
    args = parser.parse_args(argv)
    try:
        result = install_dataset(args.archive)
    except InstallError as error:
        print(str(error))
        return 2
    print("Required private data files already match; existing files were preserved." if result == "unchanged"
          else "Installed the five required analytical files and exact-date historical inputs in the private runtime folder.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
