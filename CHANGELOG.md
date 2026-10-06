# Changelog

## 0.0.1 — 2026-10-06

- Write uncompressed raw `.img` and `.iso` images to external macOS disks.
- Show disk name, capacity, device path, and connection type before selection.
- Exclude internal, virtual, read-only, undersized, startup, and source disks.
- Require exact device-path confirmation and recheck the disk before writing.
- Show a progress bar with elapsed time, transfer rate, and estimated time left.
- Flush writes and eject the target after successful completion.
- Include Homebrew installation, zsh completion, and mocked macOS CI tests.
