"""Developer-only build of the repository's prepared, date-scoped inputs.

Reads only the five prepared analytical master files. Workers consume a single
dated member set from the resulting bundle; they never run this preparation.
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
MAX_FILE_BYTES = 4 * 1024 * 1024
MAX_ROWS = 10_000
MAX_LINE_BYTES = 64 * 1024
MAX_UNCOMPRESSED_BYTES = 128 * 1024 * 1024
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_ENTRIES = 10_000
FIXED_TIMESTAMP = (2000, 1, 1, 0, 0, 0)


class BundleError(ValueError):
    """Fixed diagnostic that never includes a record or source path."""


def _reject(message="Prepared analytical inputs do not meet the bounded bundle format."):
    raise BundleError(message)


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _reject()
        result[key] = value
    return result


def _constant(_value):
    _reject()


def _regular(path, *, limit):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
        _reject()
    return info


def _read_prepared(path):
    before = _regular(path, limit=MAX_FILE_BYTES)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(path, flags), "rb") as source:
        opened = os.fstat(source.fileno())
        if (not stat.S_ISREG(opened.st_mode) or opened.st_size > MAX_FILE_BYTES
                or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)):
            _reject()
        data = source.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        _reject()
    rows = 0
    for line in data.splitlines():
        if len(line) > MAX_LINE_BYTES:
            _reject()
        if not line.strip():
            continue
        rows += 1
        if rows > MAX_ROWS:
            _reject()
        raw = json.loads(line.decode("utf-8"), object_pairs_hook=_object, parse_constant=_constant)
        if project_record(path.name, raw) != raw:
            _reject("Only prepared analytical fields are accepted.")
    return data


def _same_bytes(left, right):
    if left.stat().st_size != right.stat().st_size:
        return False
    with left.open("rb") as a, right.open("rb") as b:
        while True:
            block = a.read(1024 * 1024)
            if block != b.read(1024 * 1024):
                return False
            if not block:
                return True


def bundle_dataset(*, repo_root=ROOT):
    """Atomically publish as_of.zip; return ``bundled`` or ``unchanged``.

    Identical output preserves the bundle's timestamp. Master files and other
    private documents are never modified or enumerated.
    """
    temporary = None
    try:
        root = Path(repo_root).absolute()
        source = root / "private_data" / "toddbrook_runtime" / "data"
        for directory in (root, root / "private_data", source.parent, source):
            if not stat.S_ISDIR(directory.lstat().st_mode):
                _reject("The five prepared master files must exist in the runtime data directory.")
        destination = source.parent / "as_of.zip"
        if destination.exists() or destination.is_symlink():
            _regular(destination, limit=MAX_ARCHIVE_BYTES)
        files = {name: _read_prepared(source / name) for name in sorted(DATA_FILES)}
        descriptor, name = tempfile.mkstemp(prefix=".as-of-bundle-", suffix=".zip", dir=source.parent)
        temporary = Path(name)
        with os.fdopen(descriptor, "w+b") as output:
            entries = total = 0
            days = sorted(snapshot_days())
            if not days or len(days) != len(set(days)):
                _reject()
            with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED,
                                 compresslevel=9, allowZip64=False) as archive:
                for as_of, prepared in iter_snapshots(files, dates=days):
                    for filename in sorted(DATA_FILES):
                        content = prepared[filename]
                        entries += 1
                        total += len(content)
                        if entries > MAX_ENTRIES or total > MAX_UNCOMPRESSED_BYTES:
                            _reject("The prepared bundle exceeds its size or entry limit.")
                        info = zipfile.ZipInfo(f"{as_of.isoformat()}/data/{filename}", FIXED_TIMESTAMP)
                        info.create_system = 3
                        info.external_attr = (stat.S_IFREG | 0o600) << 16
                        info.compress_type = zipfile.ZIP_DEFLATED
                        archive.writestr(info, content, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
                        if output.tell() > MAX_ARCHIVE_BYTES:
                            _reject("The prepared bundle exceeds its archive size limit.")
            output.flush()
            if os.fstat(output.fileno()).st_size > MAX_ARCHIVE_BYTES:
                _reject("The prepared bundle exceeds its archive size limit.")
            os.fsync(output.fileno())
        # Recheck the destination immediately before comparing or publishing.
        if destination.exists() or destination.is_symlink():
            _regular(destination, limit=MAX_ARCHIVE_BYTES)
            if _same_bytes(temporary, destination):
                return "unchanged"
        os.replace(temporary, destination)
        return "bundled"
    except BundleError:
        raise
    except (OSError, ValueError, TypeError, OverflowError, RecursionError, zipfile.BadZipFile):
        raise BundleError("The prepared bundle could not be built; check the five prepared master files and output directory.") from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    try:
        result = bundle_dataset()
    except BundleError as error:
        print(str(error))
        return 2
    print(f"Prepared historical input bundle: {result}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
