import io
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock


sys.dont_write_bytecode = True
LOADED = runpy.run_path(str(Path(__file__).parents[1] / "bin" / "easydd"), run_name="easydd_test")
EASY = LOADED["main"].__globals__
Error = EASY["Error"]


class EasyDDTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        for name in ("run", "Popen"):
            guard = mock.patch.object(
                subprocess, name, side_effect=AssertionError("external process execution is forbidden"))
            guard.start()
            self.addCleanup(guard.stop)

    def image(self, name="image.img", data=None):
        path = self.directory / name
        path.write_bytes(b"\0" * 512 if data is None else data)
        return path

    @staticmethod
    def disk(identifier="disk9", **changes):
        result = {
            "DeviceIdentifier": identifier,
            "DeviceNode": "/dev/" + identifier,
            "WholeDisk": True,
            "VirtualOrPhysical": "Physical",
            "Internal": False,
            "OSInternalMedia": False,
            "RemovableMediaOrExternalDevice": True,
            "WritableMedia": True,
            "TotalSize": 4096,
            "DeviceBlockSize": 512,
            "MediaName": "Test USB",
            "BusProtocol": "USB",
            "DeviceTreePath": "IOService:/test",
            "MediaUUID": "media-uuid",
            "DiskUUID": "disk-uuid",
        }
        result.update(changes)
        return result

    @staticmethod
    def listing(*identifiers):
        return {
            "WholeDisks": list(identifiers),
            "AllDisksAndPartitions": [
                {"DeviceIdentifier": identifier} for identifier in identifiers
            ],
        }

    def test_validate_image_accepts_raw_img_and_iso(self):
        for suffix in (".img", ".ISO"):
            for size in (512, 4096, 8192):
                with self.subTest(suffix=suffix, size=size):
                    image = self.image(f"valid-{size}{suffix}", b"raw\0" + b"\0" * (size - 4))
                    source, metadata = EASY["validate_image"](image)
                    with source:
                        self.assertEqual(os.lseek(source.fileno(), 0, os.SEEK_CUR), 0)
                        self.assertEqual(source.read(4), b"raw\0")
                        self.assertEqual(metadata.st_size, size)

    def test_validate_image_rejects_suffix_empty_and_unaligned_files(self):
        cases = {
            "image.raw": b"\0" * 512,
            "empty.img": b"",
            "unaligned.iso": b"\0" * 513,
        }
        for name, data in cases.items():
            with self.subTest(name=name), self.assertRaises(Error):
                EASY["validate_image"](self.image(name, data))

    def test_validate_image_rejects_non_regular_file(self):
        image = self.image()
        real_fstat = os.fstat

        def non_regular(fd):
            metadata = real_fstat(fd)
            return types.SimpleNamespace(st_mode=0, st_size=metadata.st_size)

        with mock.patch.object(os, "fstat", side_effect=non_regular):
            with self.assertRaises(Error):
                EASY["validate_image"](image)

    def test_validate_image_does_not_follow_symlinks_or_block_on_fifo(self):
        image = self.image()
        symlink = self.directory / "link.img"
        symlink.symlink_to(image)
        fifo = self.directory / "pipe.img"
        os.mkfifo(fifo)
        for path in (symlink, fifo):
            with self.subTest(path=path.name), self.assertRaises((Error, OSError)):
                EASY["validate_image"](path)

    def test_validate_image_rejects_archives_and_dmg(self):
        signatures = (
            b"\x1f\x8b", b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08", b"BZh",
            b"\xfd7zXZ\x00", b"\x28\xb5\x2f\xfd", b"7z\xbc\xaf\x27\x1c",
            b"Rar!\x1a\x07", b"sprs",
        )
        for number, signature in enumerate(signatures):
            with self.subTest(signature=signature), self.assertRaises(Error):
                EASY["validate_image"](
                    self.image(f"compressed-{number}.img", signature + b"\0" * (512 - len(signature))))
        tar = bytearray(512)
        tar[257:262] = b"ustar"
        with self.assertRaises(Error):
            EASY["validate_image"](self.image("archive.img", tar))
        with self.assertRaises(Error):
            EASY["validate_image"](self.image("container.iso", b"koly" + b"\0" * 508))

    def test_backing_disks_resolves_all_apfs_physical_stores(self):
        volume = {"APFSPhysicalStores": [
            {"APFSPhysicalStore": "disk0s2"},
            {"APFSPhysicalStore": "disk5s1"},
        ]}
        details = {
            "/dev/disk0s2": {"ParentWholeDisk": "disk0"},
            "/dev/disk5s1": {"ParentWholeDisk": "disk5"},
            "/dev/disk0": self.disk("disk0", VirtualOrPhysical="Unknown"),
            "/dev/disk5": self.disk("disk5", VirtualOrPhysical="Unknown"),
        }
        with mock.patch.dict(EASY, {
                "diskutil": mock.Mock(return_value=self.listing("disk0", "disk5")),
                "info": mock.Mock(side_effect=lambda device: details[device])}):
            self.assertEqual(EASY["backing_disks"](volume), {"disk0", "disk5"})

    def test_backing_disks_fails_closed_for_unresolved_or_virtual_storage(self):
        cases = (
            {},
            {"APFSPhysicalStores": {"APFSPhysicalStore": "disk0s2"}},
            {"APFSPhysicalStores": [{"APFSPhysicalStore": None}]},
            {"APFSPhysicalStores": [{"APFSPhysicalStore": "not-a-partition"}]},
        )
        for volume in cases:
            with self.subTest(volume=volume), \
                    mock.patch.dict(EASY, {"diskutil": mock.Mock(return_value=self.listing())}), \
                    self.assertRaises(Error):
                EASY["backing_disks"](volume)
        volume = {"APFSPhysicalStores": [{"APFSPhysicalStore": "disk0s2"}]}
        cases = (
            ({"DeviceIdentifier": "disk0s2"}, self.listing("disk0")),
            ({"ParentWholeDisk": "disk0"}, self.listing("disk1")),
            ({"ParentWholeDisk": "disk0"}, self.listing("disk0"), "Virtual"),
            ({"ParentWholeDisk": "disk0"}, self.listing("disk0"), "Physical", "Disk Image"),
        )
        for case in cases:
            store, listing, *classification = case
            parent = self.disk("disk0")
            if classification:
                parent["VirtualOrPhysical"] = classification[0]
            if len(classification) > 1:
                parent["BusProtocol"] = classification[1]
            with self.subTest(store=store, parent=parent), mock.patch.dict(EASY, {
                    "diskutil": mock.Mock(return_value=listing),
                    "info": mock.Mock(side_effect=lambda device, store=store, parent=parent:
                                      store if device == "/dev/disk0s2" else parent)}):
                with self.assertRaises(Error):
                    EASY["backing_disks"](volume)

    def test_backing_disks_rejects_present_but_empty_apfs_metadata(self):
        for stores in ([], {}, "", None):
            volume = {"APFSPhysicalStores": stores, "DeviceIdentifier": "disk0s2"}
            diskutil = mock.Mock(return_value=self.listing("disk0"))
            info = mock.Mock(return_value=self.disk("disk0"))
            with self.subTest(stores=stores), mock.patch.dict(EASY, {
                    "diskutil": diskutil, "info": info}), self.assertRaises(Error):
                EASY["backing_disks"](volume)
            diskutil.assert_not_called()
            info.assert_not_called()

    def test_protected_disks_combines_startup_and_image_source(self):
        image = self.image()
        root = {"APFSPhysicalStores": [{"APFSPhysicalStore": "disk0s2"}]}
        source = {"DeviceIdentifier": "disk4s1", "ParentWholeDisk": "disk4"}
        stores = {
            "/dev/disk0s2": {"ParentWholeDisk": "disk0"},
            "/dev/disk0": self.disk("disk0", VirtualOrPhysical="Unknown"),
            "/dev/disk4": self.disk("disk4", VirtualOrPhysical="Unknown"),
        }

        def fake_info(device):
            return root if device == "/" else source if device == "/dev/disk4s1" else stores[device]

        df = types.SimpleNamespace(stdout="Filesystem blocks Used Available Capacity Mounted on\n/dev/disk4s1 1 1 0 100% /tmp\n")
        with mock.patch.dict(EASY, {
                "info": mock.Mock(side_effect=fake_info),
                "diskutil": mock.Mock(return_value=self.listing("disk0", "disk4")),
                "command": mock.Mock(return_value=df)}):
            self.assertEqual(EASY["protected_disks"](image), {"disk0", "disk4"})

    def test_protected_disks_fails_closed_when_root_or_source_is_unresolved(self):
        image = self.image()
        with mock.patch.dict(EASY, {
                "info": mock.Mock(return_value={}),
                "diskutil": mock.Mock(return_value=self.listing())}):
            with self.assertRaises(Error):
                EASY["protected_disks"](image)
        root = {"DeviceIdentifier": "disk0"}
        parent = self.disk("disk0", VirtualOrPhysical="Unknown")
        invalid_df = types.SimpleNamespace(stdout="Filesystem blocks\nnot-a-device 1\n")
        with mock.patch.dict(EASY, {
                "info": mock.Mock(side_effect=lambda device: root if device == "/" else parent),
                "diskutil": mock.Mock(return_value=self.listing("disk0")),
                "command": mock.Mock(return_value=invalid_df)}):
            with self.assertRaises(Error):
                EASY["protected_disks"](image)

    def test_eligible_disks_excludes_every_unsafe_class(self):
        image = self.image()
        candidates = {
            "disk1": self.disk("disk1"),
            "disk2": self.disk("disk2", Internal=True),
            "disk3": self.disk("disk3", VirtualOrPhysical="Virtual"),
            "disk4": self.disk("disk4", WritableMedia=False),
            "disk5": self.disk("disk5", TotalSize=511),
            "disk6": self.disk("disk6"),
            "disk7": self.disk("disk7", RemovableMediaOrExternalDevice=False),
            "disk8": self.disk("disk8", OSInternalMedia=True),
            "disk9": self.disk("disk9", WholeDisk=False),
            "disk10": self.disk("other"),
            "disk11": self.disk("disk11", DeviceNode="/dev/disk99"),
            "disk12": self.disk("disk12", DeviceBlockSize=768),
        }
        listing = {
            "WholeDisks": list(candidates) + ["disk13"],
            "AllDisksAndPartitions": [
                {"DeviceIdentifier": identifier} for identifier in candidates
            ],
        }

        def fake_diskutil(*args):
            self.assertEqual(args, ("list", "-plist", "external", "physical"))
            return listing

        with mock.patch.dict(EASY, {
                "protected_disks": mock.Mock(return_value={"disk6"}),
                "diskutil": fake_diskutil,
                "info": mock.Mock(side_effect=lambda device: candidates[device.removeprefix("/dev/")])}):
            self.assertEqual(EASY["eligible_disks"](image, 512), [candidates["disk1"]])

    def test_external_apfs_startup_store_is_never_eligible(self):
        image = self.image()
        root = {"APFSPhysicalStores": [
            {"APFSPhysicalStore": "disk5s2"},
            {"APFSPhysicalStore": "disk6s2"},
        ]}
        details = {
            "/": root,
            "/dev/disk0s1": {"DeviceIdentifier": "disk0s1", "ParentWholeDisk": "disk0"},
            "/dev/disk5s2": {"ParentWholeDisk": "disk5"},
            "/dev/disk6s2": {"ParentWholeDisk": "disk6"},
            "/dev/disk0": self.disk("disk0", VirtualOrPhysical="Unknown"),
            "/dev/disk5": self.disk("disk5", VirtualOrPhysical="Unknown"),
            "/dev/disk6": self.disk("disk6", VirtualOrPhysical="Unknown"),
            "/dev/disk9": self.disk("disk9"),
        }
        df = types.SimpleNamespace(stdout="Filesystem blocks Used Available Capacity Mounted on\n"
                                           "/dev/disk0s1 1 1 0 100% /tmp\n")

        def fake_diskutil(*args):
            if args == ("list", "-plist", "physical"):
                return self.listing("disk0", "disk5", "disk6", "disk9")
            if args == ("list", "-plist", "external", "physical"):
                return self.listing("disk5", "disk6", "disk9")
            if args[:2] == ("info", "-plist"):
                return details[args[2]]
            self.fail(f"unexpected diskutil call: {args}")

        with mock.patch.dict(EASY, {
                "diskutil": fake_diskutil,
                "command": mock.Mock(return_value=df)}):
            self.assertEqual(EASY["eligible_disks"](image, 512), [details["/dev/disk9"]])

    def test_realistic_apfs_shapes_protect_startup_and_downloads_source(self):
        image = self.image()
        source_parent = self.disk("disk73")
        del source_parent["VirtualOrPhysical"]
        details = {
            "/": {"APFSPhysicalStores": [{"APFSPhysicalStore": "disk42s2"}]},
            "/dev/disk42s2": {"ParentWholeDisk": "disk42"},
            "/dev/disk73s1": {"DeviceIdentifier": "disk73s1", "ParentWholeDisk": "disk73"},
            "/dev/disk42": self.disk("disk42", VirtualOrPhysical="Unknown"),
            "/dev/disk73": source_parent,
            "/dev/disk91": self.disk("disk91", MediaName="Regression USB"),
        }
        df = types.SimpleNamespace(stdout="Filesystem blocks Used Available Capacity Mounted on\n"
                                           "/dev/disk73s1 1 1 0 100% /Users/test/Downloads\n")

        def fake_diskutil(*args):
            if args == ("list", "-plist", "physical"):
                return self.listing("disk42", "disk73", "disk91")
            if args == ("list", "-plist", "external", "physical"):
                return self.listing("disk73", "disk91")
            if args[:2] == ("info", "-plist"):
                return details[args[2]]
            self.fail(f"unexpected diskutil call: {args}")

        with mock.patch.dict(EASY, {
                "diskutil": fake_diskutil,
                "command": mock.Mock(return_value=df)}):
            self.assertEqual(EASY["eligible_disks"](image, 512), [details["/dev/disk91"]])

    def test_eligible_disks_rejects_malformed_external_listing(self):
        listing = {
            "WholeDisks": ["disk9s1"],
            "AllDisksAndPartitions": [{"DeviceIdentifier": "disk9s1"}],
        }
        with mock.patch.dict(EASY, {
                "protected_disks": mock.Mock(return_value=set()),
                "diskutil": mock.Mock(return_value=listing)}):
            with self.assertRaises(Error):
                EASY["eligible_disks"](self.image(), 512)

    def test_recheck_rejects_changed_identity_and_ineligibility(self):
        selected = self.disk()
        changed = self.disk(MediaUUID="replacement")
        for current in ([changed], []):
            with self.subTest(current=current), mock.patch.dict(EASY, {
                    "eligible_disks": mock.Mock(return_value=current)}):
                with self.assertRaises(Error):
                    EASY["recheck"](selected, self.image(), 512)

    def test_write_image_uses_pv_pipeline_and_raw_dd_target(self):
        source = io.BytesIO(b"image")
        reader_stdout = mock.Mock()
        reader = mock.Mock(stdout=reader_stdout)
        reader.wait.return_value = 0
        reader.poll.return_value = 0
        writer = mock.Mock()
        writer.wait.return_value = 0
        process = types.SimpleNamespace(Popen=mock.Mock(side_effect=[reader, writer]),
                                        PIPE=subprocess.PIPE)
        with mock.patch.dict(EASY, {"subprocess": process}):
            EASY["write_image"](source, 512, "/dev/rdisk9", "/fake/pv")
            self.assertEqual(process.Popen.call_args_list, [
                mock.call(["/fake/pv", "--progress", "--timer", "--eta", "--rate",
                           "--bytes", "--size", "512", "--stop-at-size"], stdin=source,
                          stdout=subprocess.PIPE),
                mock.call(["/usr/bin/sudo", "-n", "/bin/dd", "of=/dev/rdisk9",
                           "bs=4m", "iflag=fullblock", "conv=fsync"],
                          stdin=reader_stdout),
            ])
            self.assertEqual(reader_stdout.close.call_count, 2)

    def test_keyboard_interrupt_waits_for_writer_and_reaps_reader(self):
        reader = mock.Mock(stdout=mock.Mock())
        reader.poll.return_value = None
        writer = mock.Mock()
        writer.wait.side_effect = [KeyboardInterrupt, 0]
        process = types.SimpleNamespace(Popen=mock.Mock(side_effect=[reader, writer]),
                                        PIPE=subprocess.PIPE)
        ignore = object()
        signals = types.SimpleNamespace(
            SIGINT=2,
            SIG_IGN=ignore,
            signal=mock.Mock(side_effect=["previous-handler", None]),
        )
        with mock.patch.dict(EASY, {"subprocess": process, "signal": signals}):
            with self.assertRaises(KeyboardInterrupt):
                EASY["write_image"](io.BytesIO(), 512, "/dev/rdisk9", "/fake/pv")
        self.assertEqual(writer.wait.call_count, 2)
        reader.terminate.assert_called_once_with()
        reader.wait.assert_called_once_with()
        self.assertEqual(signals.signal.call_args_list, [
            mock.call(2, ignore),
            mock.call(2, "previous-handler"),
        ])

    def test_writer_or_reader_failure_is_an_error(self):
        for writer_status, reader_status in ((1, 0), (0, 1), (1, 1)):
            with self.subTest(writer=writer_status, reader=reader_status):
                reader = mock.Mock(stdout=mock.Mock())
                reader.wait.return_value = reader_status
                reader.poll.return_value = 0
                writer = mock.Mock()
                writer.wait.return_value = writer_status
                process = mock.Mock(wraps=subprocess)
                process.Popen.side_effect = [reader, writer]
                with mock.patch.dict(EASY, {"subprocess": process}), self.assertRaises(Error):
                    EASY["write_image"](io.BytesIO(), 512, "/dev/rdisk9", "/fake/pv")

    def test_main_full_flow_orders_checks_and_uses_explicit_confirmation(self):
        image = self.image()
        selected = self.disk()
        events = []

        def command(args, **kwargs):
            events.append(tuple(args))

        def recheck(*args):
            events.append("recheck")

        def write_image(source, size, raw_device, pv):
            events.append(("write", size, raw_device, pv, source.closed))

        fake_stdin = mock.Mock()
        fake_stdin.isatty.return_value = True
        with mock.patch.object(sys, "argv", ["easydd", str(image)]), \
                mock.patch.object(sys, "platform", "darwin"), \
                mock.patch.object(sys, "stdin", fake_stdin), \
                mock.patch.object(os, "geteuid", return_value=501), \
                mock.patch.object(EASY["shutil"], "which", return_value="/fake/pv"), \
                mock.patch("builtins.input", side_effect=["1", "/dev/disk9"]) as input_mock, \
                mock.patch("builtins.print") as printing, \
                mock.patch.dict(EASY, {
                    "eligible_disks": mock.Mock(return_value=[selected]),
                    "command": command,
                    "recheck": recheck,
                    "write_image": write_image,
                }):
            EASY["main"]()

        self.assertEqual(input_mock.call_args_list[-1], mock.call("Type /dev/disk9 to confirm: "))
        printing.assert_any_call("1. Test USB | 0.00 GB | /dev/disk9 | USB")
        printing.assert_any_call("\nALL DATA on /dev/disk9 (Test USB, 0.00 GB) will be erased.")
        self.assertEqual(events, [
            ("/usr/bin/sudo", "-v"),
            "recheck",
            (EASY["DISKUTIL"], "unmountDisk", "/dev/disk9"),
            "recheck",
            ("write", 512, "/dev/rdisk9", "/fake/pv", False),
            (EASY["DISKUTIL"], "eject", "/dev/disk9"),
        ])

    def test_main_refuses_symlink_image_before_any_privileged_command(self):
        image = self.image()
        symlink = self.directory / "link.img"
        symlink.symlink_to(image)
        command = mock.Mock(side_effect=AssertionError("privileged command ran"))
        with mock.patch.object(sys, "argv", ["easydd", str(symlink)]), \
                mock.patch.object(sys, "platform", "darwin"), \
                mock.patch.object(os, "geteuid", return_value=501), \
                mock.patch.dict(EASY, {
                    "command": command,
                    "write_image": mock.Mock(side_effect=AssertionError("writer ran")),
                }):
            with self.assertRaises(OSError):
                EASY["main"]()
        command.assert_not_called()

    def test_main_cancellation_never_runs_privileged_commands_or_writer(self):
        for answers in (["q"], ["1", "no"]):
            with self.subTest(answers=answers):
                image = self.image("cancel.img")
                command = mock.Mock(side_effect=AssertionError("privileged command ran"))
                writer = mock.Mock(side_effect=AssertionError("writer ran"))
                fake_stdin = mock.Mock()
                fake_stdin.isatty.return_value = True
                with mock.patch.object(sys, "argv", ["easydd", str(image)]), \
                        mock.patch.object(sys, "platform", "darwin"), \
                        mock.patch.object(sys, "stdin", fake_stdin), \
                        mock.patch.object(os, "geteuid", return_value=501), \
                        mock.patch.object(EASY["shutil"], "which", return_value="/fake/pv"), \
                        mock.patch("builtins.input", side_effect=answers), \
                        mock.patch("builtins.print"), \
                        mock.patch.dict(EASY, {
                            "eligible_disks": mock.Mock(return_value=[self.disk()]),
                            "command": command,
                            "write_image": writer,
                        }):
                    EASY["main"]()
                command.assert_not_called()
                writer.assert_not_called()

    def test_main_rejects_wrong_platform_root_and_noninteractive_input(self):
        image = self.image()
        cases = (
            ("linux", 501, True, "macOS"),
            ("darwin", 0, True, "normal user"),
            ("darwin", 501, False, "interactive"),
        )
        for platform, euid, interactive, message in cases:
            with self.subTest(platform=platform, euid=euid, interactive=interactive):
                fake_stdin = mock.Mock()
                fake_stdin.isatty.return_value = interactive
                with mock.patch.object(sys, "argv", ["easydd", str(image)]), \
                        mock.patch.object(sys, "platform", platform), \
                        mock.patch.object(sys, "stdin", fake_stdin), \
                        mock.patch.object(os, "geteuid", return_value=euid), \
                        mock.patch.object(EASY["shutil"], "which", return_value="/fake/pv"), \
                        mock.patch.dict(EASY, {
                            "eligible_disks": mock.Mock(side_effect=AssertionError("disk scan ran")),
                            "write_image": mock.Mock(side_effect=AssertionError("writer ran")),
                        }):
                    with self.assertRaisesRegex(Error, message):
                        EASY["main"]()

    def test_main_detects_image_change_before_unmount(self):
        image = self.image()
        original_validate = EASY["validate_image"]

        def validate(path):
            source, metadata = original_validate(path)
            image.write_bytes(b"changed" + b"\0" * 505)
            return source, metadata

        command = mock.Mock()
        fake_stdin = mock.Mock()
        fake_stdin.isatty.return_value = True
        with mock.patch.object(sys, "argv", ["easydd", str(image)]), \
                mock.patch.object(sys, "platform", "darwin"), \
                mock.patch.object(sys, "stdin", fake_stdin), \
                mock.patch.object(os, "geteuid", return_value=501), \
                mock.patch.object(EASY["shutil"], "which", return_value="/fake/pv"), \
                mock.patch("builtins.input", side_effect=["1", "/dev/disk9"]), \
                mock.patch("builtins.print"), \
                mock.patch.dict(EASY, {
                    "validate_image": validate,
                    "eligible_disks": mock.Mock(return_value=[self.disk()]),
                    "recheck": mock.Mock(),
                    "command": command,
                    "write_image": mock.Mock(side_effect=AssertionError("writer ran")),
                }):
            with self.assertRaisesRegex(Error, "image changed"):
                EASY["main"]()
        command.assert_called_once_with(["/usr/bin/sudo", "-v"])

    def test_main_too_small_target_and_pre_or_post_unmount_recheck_never_write(self):
        image = self.image()
        scenarios = (
            ([], None),
            ([self.disk()], 1),
            ([self.disk()], 2),
        )
        for disks, failing_recheck in scenarios:
            with self.subTest(disks=bool(disks), failing_recheck=failing_recheck):
                command = mock.Mock()
                writer = mock.Mock(side_effect=AssertionError("writer ran"))
                checks = 0

                def recheck(*args):
                    nonlocal checks
                    checks += 1
                    if checks == failing_recheck:
                        raise Error("unsafe")

                fake_stdin = mock.Mock()
                fake_stdin.isatty.return_value = True
                inputs = ["1", "/dev/disk9"] if disks else []
                with mock.patch.object(sys, "argv", ["easydd", str(image)]), \
                        mock.patch.object(sys, "platform", "darwin"), \
                        mock.patch.object(sys, "stdin", fake_stdin), \
                        mock.patch.object(os, "geteuid", return_value=501), \
                        mock.patch.object(EASY["shutil"], "which", return_value="/fake/pv"), \
                        mock.patch("builtins.input", side_effect=inputs), \
                        mock.patch("builtins.print"), \
                        mock.patch.dict(EASY, {
                            "eligible_disks": mock.Mock(return_value=disks),
                            "recheck": recheck,
                            "command": command,
                            "write_image": writer,
                        }):
                    with self.assertRaises(Error):
                        EASY["main"]()
                writer.assert_not_called()
                self.assertFalse(any(call.args[0][1:2] == ["eject"] for call in command.call_args_list))

    def test_main_write_failure_never_ejects_or_prints_success(self):
        image = self.image()
        command = mock.Mock()
        fake_stdin = mock.Mock()
        fake_stdin.isatty.return_value = True
        with mock.patch.object(sys, "argv", ["easydd", str(image)]), \
                mock.patch.object(sys, "platform", "darwin"), \
                mock.patch.object(sys, "stdin", fake_stdin), \
                mock.patch.object(os, "geteuid", return_value=501), \
                mock.patch.object(EASY["shutil"], "which", return_value="/fake/pv"), \
                mock.patch("builtins.input", side_effect=["1", "/dev/disk9"]), \
                mock.patch("builtins.print") as printing, \
                mock.patch.dict(EASY, {
                    "eligible_disks": mock.Mock(return_value=[self.disk()]),
                    "recheck": mock.Mock(),
                    "command": command,
                    "write_image": mock.Mock(side_effect=Error("write failed")),
                }):
            with self.assertRaises(Error):
                EASY["main"]()
        self.assertFalse(any(call.args[0][1:2] == ["eject"] for call in command.call_args_list))
        self.assertFalse(any(str(call).find("Done:") >= 0 for call in printing.call_args_list))

    def test_main_sudo_failure_never_unmounts_or_writes(self):
        image = self.image()
        commands = []
        writer = mock.Mock(side_effect=AssertionError("writer ran"))
        fake_stdin = mock.Mock()
        fake_stdin.isatty.return_value = True

        def command(args, **kwargs):
            commands.append(args)
            raise Error("sudo failed")

        with mock.patch.object(sys, "argv", ["easydd", str(image)]), \
                mock.patch.object(sys, "platform", "darwin"), \
                mock.patch.object(sys, "stdin", fake_stdin), \
                mock.patch.object(os, "geteuid", return_value=501), \
                mock.patch.object(EASY["shutil"], "which", return_value="/fake/pv"), \
                mock.patch("builtins.input", side_effect=["1", "/dev/disk9"]), \
                mock.patch("builtins.print"), \
                mock.patch.dict(EASY, {
                    "eligible_disks": mock.Mock(return_value=[self.disk()]),
                    "command": command,
                    "write_image": writer,
                }):
            with self.assertRaisesRegex(Error, "sudo failed"):
                EASY["main"]()
        self.assertEqual(commands, [["/usr/bin/sudo", "-v"]])
        writer.assert_not_called()

    def test_main_detects_image_change_during_write_before_eject(self):
        image = self.image()
        command = mock.Mock()
        fake_stdin = mock.Mock()
        fake_stdin.isatty.return_value = True

        def writer(*args):
            image.write_bytes(b"changed" + b"\0" * 505)

        with mock.patch.object(sys, "argv", ["easydd", str(image)]), \
                mock.patch.object(sys, "platform", "darwin"), \
                mock.patch.object(sys, "stdin", fake_stdin), \
                mock.patch.object(os, "geteuid", return_value=501), \
                mock.patch.object(EASY["shutil"], "which", return_value="/fake/pv"), \
                mock.patch("builtins.input", side_effect=["1", "/dev/disk9"]), \
                mock.patch("builtins.print"), \
                mock.patch.dict(EASY, {
                    "eligible_disks": mock.Mock(return_value=[self.disk()]),
                    "recheck": mock.Mock(),
                    "command": command,
                    "write_image": writer,
                }):
            with self.assertRaisesRegex(Error, "changed during writing"):
                EASY["main"]()
        self.assertFalse(any(call.args[0][1:2] == ["eject"] for call in command.call_args_list))

    def test_main_reports_completed_write_when_eject_fails(self):
        image = self.image()
        fake_stdin = mock.Mock()
        fake_stdin.isatty.return_value = True

        def command(args, **kwargs):
            if args[1:2] == ["eject"]:
                raise Error("eject failed")

        with mock.patch.object(sys, "argv", ["easydd", str(image)]), \
                mock.patch.object(sys, "platform", "darwin"), \
                mock.patch.object(sys, "stdin", fake_stdin), \
                mock.patch.object(os, "geteuid", return_value=501), \
                mock.patch.object(EASY["shutil"], "which", return_value="/fake/pv"), \
                mock.patch("builtins.input", side_effect=["1", "/dev/disk9"]), \
                mock.patch("builtins.print") as printing, \
                mock.patch.dict(EASY, {
                    "eligible_disks": mock.Mock(return_value=[self.disk()]),
                    "recheck": mock.Mock(),
                    "command": command,
                    "write_image": mock.Mock(),
                }):
            with self.assertRaisesRegex(Error, "written and flushed.*ejection failed"):
                EASY["main"]()
        self.assertFalse(any("Done:" in str(call) for call in printing.call_args_list))


if __name__ == "__main__":
    unittest.main()
