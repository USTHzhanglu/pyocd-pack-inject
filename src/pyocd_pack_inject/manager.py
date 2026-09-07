"""把本地 .pack 安装进 pyOCD 的全局 pack 缓存。

机制背景
--------
pyOCD 的 "managed packs" 由 cmsis-pack-manager 提供: 当目标型号不在 pyOCD
内置列表时, pyOCD(board.py -> ManagedPacks.populate_target)会扫描
cmsis-pack-manager 缓存目录 data_path 下已注册的 pack。注册需满足两个条件:

    1. data_path/index.json 里有该 pack 的记录 (from_pack 字段)
       (pyOCD 用 cache.index 枚举 installed packs)
    2. data_path/<vendor>/<pack>/<version>.pack 文件真实存在
       (ManagedPacks.get_installed_packs 用 os.path.isfile 判定)

官方 `pyocd pack install` 只能安装 Keil 公共索引里的包, 而厂商官网、
自研、或打过补丁(如修正 RAMstart/RAMsize)的本地 .pack 不在索引中,
官方命令装不进去。本工具针对这类本地包, 手动完成注册:

    1. 复制 .pack -> data_path/<vendor>/<pack>/<version>.pack
    2. index.json 里 merge 一条 from_pack 记录

(尝试过 Cache.add_pack_from_path(), 但 cmsis-pack-manager 的 rust 解析器
对部分厂商 pack 会静默失败、不写 index; 手动维护同样满足 pyOCD 的判定,
且 pyOCD 的设备详情是自己用 CmsisPack 重新解析 .pack 得到的。)

装完后 pyOCD 只需 target_override=<型号>, 无需 --pack 即可识别该设备。
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import threading
import zipfile
from dataclasses import dataclass
from xml.etree import ElementTree as ET

__all__ = [
    "PackMeta",
    "PackManager",
    "PackManagerError",
    "cpm_available",
    "default_data_path",
]


class PackManagerError(RuntimeError):
    """Raised on any operation failure."""


def cpm_available() -> bool:
    """Whether the cmsis-pack-manager package is importable."""
    try:
        import cmsis_pack_manager  # noqa: F401
        return True
    except ImportError:
        return False


@dataclass(frozen=True)
class PackMeta:
    """Identity of a pack, read from its embedded PDSC."""
    vendor: str
    pack: str
    version: str

    @property
    def ref(self) -> str:
        return "%s.%s" % (self.vendor, self.pack)

    @property
    def full_ref(self) -> str:
        return "%s.%s.%s" % (self.vendor, self.pack, self.version)


def _strip_ns(tag: str) -> str:
    return tag.split("}", 1)[-1]


def read_pack_meta(pack_path: str) -> PackMeta:
    """Extract (vendor, pack, version) from the .pack's embedded PDSC."""
    if not os.path.isfile(pack_path):
        raise PackManagerError("pack file not found: %s" % pack_path)
    try:
        with zipfile.ZipFile(pack_path) as z:
            pdsc_name = next((n for n in z.namelist() if n.lower().endswith(".pdsc")), None)
            if pdsc_name is None:
                raise PackManagerError("pack contains no .pdsc: %s" % pack_path)
            root = ET.fromstring(z.read(pdsc_name))
    except zipfile.BadZipFile as e:
        raise PackManagerError("not a valid zip/pack file: %s (%s)" % (pack_path, e))

    def _text(tag: str) -> str:
        for el in root.iter():
            if _strip_ns(el.tag) == tag and el.text and el.text.strip():
                return el.text.strip()
        return ""

    vendor = _text("vendor")
    name = _text("name")
    version = ""
    # <releases><release version="...">; take the newest listed.
    for el in root.iter():
        if _strip_ns(el.tag) == "release" and el.get("version"):
            version = max(version, el.get("version") or "")
    if not (vendor and name and version):
        raise PackManagerError(
            "unable to read vendor/pack/version from PDSC in %s" % pack_path)
    return PackMeta(vendor=vendor, pack=name, version=version)


def _user_data_dir(appname: str) -> str:
    """Minimal appdirs.user_data_dir() replacement (Windows/Linux/macOS)."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")
        return os.path.join(base, appname)
    if sys.platform == "darwin":
        return os.path.join(os.path.expanduser("~/Library/Application Support"), appname)
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, appname)


def default_data_path() -> str:
    """The cmsis-pack-manager data directory pyOCD scans for managed packs.

    Prefers the real value from an installed cmsis-pack-manager (its appdirs
    layout may nest the app name twice on some platforms); falls back to a
    best-effort platform default only when cpm is not installed.
    """
    if cpm_available():
        try:
            import cmsis_pack_manager
            return cmsis_pack_manager.Cache(True, False).data_path
        except Exception:
            pass
    return _user_data_dir("cmsis-pack-manager")


class PackManager:
    """Manage local packs inside the pyOCD/cmsis-pack-manager global cache."""

    def __init__(self, data_path: str | None = None):
        if not cpm_available():
            raise PackManagerError(
                "cmsis-pack-manager is not installed. Run: pip install "
                "'cmsis-pack-manager>=0.5.2,<1.0' (pyOCD needs it to scan "
                "the global pack cache).")
        self._data_path = data_path or default_data_path()
        # index.json is tens of MB (whole public index); cache it per-process
        # and invalidate on file mtime so install/remove do not re-read and
        # re-write the full file for every pack.
        self._index_path = os.path.join(self._data_path, "index.json")
        self._index_cache = None
        self._index_mtime = None
        # Guards index cache access; the GUI installs from a worker thread.
        self._lock = threading.RLock()

    # ---------------- index cache ----------------

    def _load_index(self) -> dict:
        """Load index.json, using the cached copy while the file is unchanged."""
        with self._lock:
            try:
                mt = os.path.getmtime(self._index_path)
            except OSError:
                mt = None
            if self._index_cache is not None and mt == self._index_mtime:
                return self._index_cache
            try:
                with open(self._index_path, encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, ValueError):
                data = {}
            if not isinstance(data, dict):
                data = {}
            self._index_cache = data
            self._index_mtime = mt
            return data

    def _save_index(self) -> None:
        """Atomically write the cached index back to disk.

        Serialise in memory first: streaming json.dump to a file handle is
        ~6x slower on this ~30 MB index (character-wise writes).
        """
        with self._lock:
            payload = json.dumps(self._index_cache, indent=2)
            tmp = self._index_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(payload)
            os.replace(tmp, self._index_path)
            try:
                self._index_mtime = os.path.getmtime(self._index_path)
            except OSError:
                self._index_mtime = None

    @property
    def data_path(self) -> str:
        return self._data_path

    # ---------------- install ----------------

    def install(self, pack_path: str, replace_same_pack: bool = True) -> PackMeta:
        """Register one local .pack in the global cache."""
        metas, _ = self.install_many([pack_path], replace_same_pack=replace_same_pack)
        return metas[0]

    def install_many(self, pack_paths, replace_same_pack: bool = True):
        """Register several local .pack files with a single index read/write.

        Returns (installed_metas, failures) where failures is a list of
        (path, error). All valid packs are installed; invalid ones are
        reported per file. The index.json cache is loaded once and written
        back once (it is a ~30 MB public index, so per-pack full rewrites
        are what made Add slow).
        """
        metas = []
        failures = []
        with self._lock:
            for p in pack_paths:
                p = os.path.abspath(p)
                try:
                    meta = read_pack_meta(p)
                except PackManagerError as e:
                    failures.append((os.path.basename(p), str(e)))
                    continue
                metas.append((p, meta))

            if not metas:
                return [], failures

            index = self._load_index()

            for p, meta in metas:
                # Keep a single version per pack: drop previous files/index.
                if replace_same_pack:
                    self._remove_pack_files(meta.vendor, meta.pack)
                    self._drop_index_entries(meta.vendor, meta.pack, index=index)

                # 1) Copy the .pack file into place.
                dest_dir = os.path.join(self._data_path, meta.vendor, meta.pack)
                os.makedirs(dest_dir, exist_ok=True)
                dest = os.path.join(dest_dir, meta.version + ".pack")
                shutil.copy2(p, dest)

                # 2) Merge a from_pack record into the in-memory index.
                self._merge_index_entry(meta, index=index)

            # Single write for all packs.
            self._save_index()
        return [m for _, m in metas], failures

    def _merge_index_entry(self, meta: PackMeta, index: dict | None = None) -> None:
        """Add one placeholder record to the (cached) index.

        The value mirrors cmsis-pack's DumpDevice JSON shape with empty
        memories/algorithms/processors: pyOCD's `pack update` (rust
        dump_devices) deserialises the WHOLE index.json before merging - if
        any record is missing a required field the parse fails and all old
        records are dropped. Keeping the placeholder serde-compatible
        protects it (and all other records) across `pyocd pack update`.
        """
        if index is None:
            index = self._load_index()
        # Record key is the full pack ref.
        key = meta.full_ref
        index[key] = {
            "name": meta.full_ref,
            "memories": {},
            "algorithms": [],
            "processors": [],
            "from_pack": {
                "vendor": meta.vendor,
                "pack": meta.pack,
                "version": meta.version,
                "url": "",
            },
            "vendor": meta.vendor,
            "family": meta.full_ref,
            "sub_family": None,
        }

    # ---------------- query ----------------

    def list_installed(self):
        """Return [(PackMeta, abs_path), ...] for every installed .pack file.

        Mirrors pyOCD's installed check: a pack counts when its file exists at
        data_path/<vendor>/<pack>/<version>.pack.
        """
        results = []
        if not os.path.isdir(self._data_path):
            return results
        for vendor in sorted(os.listdir(self._data_path)):
            vdir = os.path.join(self._data_path, vendor)
            if not os.path.isdir(vdir):
                continue
            for pack in sorted(os.listdir(vdir)):
                pdir = os.path.join(vdir, pack)
                if not os.path.isdir(pdir):
                    continue
                for fn in sorted(os.listdir(pdir)):
                    if fn.lower().endswith(".pack"):
                        path = os.path.join(pdir, fn)
                        results.append(
                            (PackMeta(vendor, pack, fn[:-len(".pack")]), path))
        return results

    # ---------------- remove ----------------

    def remove(self, vendor: str, pack: str, version: str | None = None) -> int:
        """Remove installed pack(s). Returns number of .pack files removed."""
        with self._lock:
            removed = self._remove_pack_files(vendor, pack, version)
            index = self._load_index()
            changed = self._drop_index_entries(vendor, pack, version, index=index)
            if changed:
                self._save_index()
            return removed

    def _remove_pack_files(self, vendor: str, pack: str,
                           version: str | None = None) -> int:
        pdir = os.path.join(self._data_path, vendor, pack)
        removed = 0
        if not os.path.isdir(pdir):
            return 0
        for fn in list(os.listdir(pdir)):
            if version is not None and not fn.startswith(version + "."):
                continue
            path = os.path.join(pdir, fn)
            try:
                os.remove(path)
                removed += 1
            except OSError as e:
                raise PackManagerError("failed to remove %s: %s" % (path, e))
        # Clean empty parent dirs (best effort).
        for d in (pdir, os.path.dirname(pdir)):
            try:
                if os.path.isdir(d):
                    os.rmdir(d)
            except OSError:
                pass
        return removed

    def _drop_index_entries(self, vendor: str, pack: str,
                            version: str | None = None,
                            index: dict | None = None) -> bool:
        """Remove only our own placeholder index records (in memory).

        Public-index records (downloaded by `pyocd pack update`) carry real
        memories/algorithms/processors data and must NOT be deleted when a
        locally installed pack is removed. A placeholder written by
        install() has key '<vendor>.<pack>.<version>' and empty
        memories/algorithms/processors.

        Returns True when at least one record was removed. Callers are
        responsible for persisting the index with _save_index().
        """
        if index is None:
            index = self._load_index()
        prefix = (vendor + "." + pack + ".").lower()
        changed = False
        for key in list(index.keys()):
            info = index.get(key)
            if not isinstance(info, dict):
                continue
            # Placeholder entries only; never touch public-index records.
            if info.get("memories") != {} or info.get("algorithms") != [] \
                    or info.get("processors") != []:
                continue
            if not key.lower().startswith(prefix):
                continue
            if version is not None and not key.lower().endswith("." + version.lower()):
                continue
            del index[key]
            changed = True
        return changed
