"""Command line interface for pyocd_pack_inject."""

from __future__ import annotations

import argparse
import sys

from .manager import (PackManager, PackManagerError, cpm_available,
                      default_data_path, read_pack_meta)

PROG = "ppi"


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--data-path", default=None,
        help="cmsis-pack-manager data directory (default: %s)"
             % default_data_path())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Install local CMSIS-Pack files into the pyOCD global "
                    "pack cache so pyOCD discovers them without --pack.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_install = sub.add_parser("install", help="register local .pack file(s)")
    _add_common(p_install)
    p_install.add_argument("packs", nargs="+", metavar="PACK",
                           help="path(s) to .pack file(s)")
    p_install.add_argument("--keep-versions", action="store_true",
                           help="keep older versions of the same pack "
                                "(default: replace)")

    p_list = sub.add_parser("list", help="list globally installed packs")
    _add_common(p_list)
    p_list.add_argument("--path", action="store_true", help="also print file path")

    p_remove = sub.add_parser("remove", help="uninstall a pack by ref")
    _add_common(p_remove)
    p_remove.add_argument("ref", metavar="REF",
                          help="pack ref, e.g. HDSC.HC32F460 or "
                               "HDSC.HC32F460.1.0.8")

    p_path = sub.add_parser("path", help="print the global data directory")

    p_gui = sub.add_parser(
        "gui", help="open the graphical pack manager (install/remove/list)")
    _add_common(p_gui)
    return parser


def _parse_ref(ref: str):
    parts = ref.split(".")
    if len(parts) < 2 or len(parts) > 3:
        raise PackManagerError(
            "invalid ref '%s'; expected Vendor.Pack or Vendor.Pack.Version" % ref)
    return parts[0], parts[1], (parts[2] if len(parts) == 3 else None)


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "path":
            print(default_data_path())
            return 0

        if args.command == "gui":
            # Imported lazily: keeps the CLI usable without GUI extras.
            from .gui import main as gui_main
            return gui_main(data_path=args.data_path)

        if not cpm_available():
            raise PackManagerError(
                "cmsis-pack-manager is not installed. Run: pip install "
                "'cmsis-pack-manager>=0.5.2,<1.0'")

        mgr = PackManager(data_path=args.data_path)

        if args.command == "install":
            metas, failures = mgr.install_many(
                args.packs, replace_same_pack=not args.keep_versions)
            for meta in metas:
                dest = "%s/%s/%s/%s.pack" % (mgr.data_path, meta.vendor,
                                             meta.pack, meta.version)
                print("installed %s -> %s" % (meta.full_ref, dest))
            for name, err in failures:
                print("%s: error: failed to install %s: %s" % (PROG, name, err),
                      file=sys.stderr)
            return 1 if failures else 0

        if args.command == "list":
            packs = mgr.list_installed()
            if not packs:
                print("(no packs installed in %s)" % mgr.data_path)
                return 0
            for meta, path in packs:
                line = meta.full_ref
                if args.path:
                    line += "  " + path
                print(line)
            return 0

        if args.command == "remove":
            vendor, pack, version = _parse_ref(args.ref)
            n = mgr.remove(vendor, pack, version)
            if n:
                print("removed %d file(s) for %s" % (n, args.ref))
            else:
                print("nothing removed for %s" % args.ref)
            return 0

        parser.print_help()
        return 2
    except PackManagerError as e:
        print("%s: error: %s" % (PROG, e), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("aborted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
