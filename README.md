# easydd

**Write an image to an external disk, with a clear picker and progress bar.**

[![CI](https://github.com/VijitSingh97/easydd/actions/workflows/ci.yml/badge.svg)](https://github.com/VijitSingh97/easydd/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/VijitSingh97/easydd)](https://github.com/VijitSingh97/easydd/releases)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

```console
$ easydd installer.img
Image: /Users/you/Downloads/installer.img (4.29 GB)

1. USB Flash Drive | 64.00 GB | /dev/disk4 | USB

Select disk number (q to cancel): 1

ALL DATA on /dev/disk4 (USB Flash Drive, 64.00 GB) will be erased.
Type /dev/disk4 to confirm: /dev/disk4
```

For **macOS 14 or later**. Choose an eligible external disk, confirm its exact
path, and watch the progress bar. After a successful write, easydd flushes the
data and ejects the disk.

> **Writing erases all data on the selected disk.** Check the disk's name,
> capacity, and device path before confirming. Back up anything you need first.

## Install with Homebrew

```sh
brew tap vijitsingh97/easydd https://github.com/VijitSingh97/easydd.git
brew install vijitsingh97/easydd/easydd
```

Homebrew installs Python 3.13, `pv`, the command, and zsh filename completion.
macOS supplies `diskutil`, `sudo`, and `dd`.

## Usage

```sh
easydd filename.img
easydd "image with spaces.iso"
easydd --help
easydd --version
```

Run as your normal user. easydd requests your administrator password through
`sudo` only after you confirm the target. It offers no unattended write mode.
Type `q` at the disk picker, or anything other than the exact requested device
path at confirmation, to cancel without writing.

The picker shows each disk's **name, size, path, and connection type**. Only
whole, physical, external, writable disks that can fit the image are eligible.
Internal disks, virtual disk images, startup disks, and disks containing the
source image are excluded. Startup protection resolves APFS physical stores,
including an external startup disk or a container backed by multiple disks.

If storage metadata cannot be resolved safely, the command stops. Network
sources, images stored inside mounted disk images, and unresolved legacy
CoreStorage/RAID storage are unsupported. Copy the image onto a directly backed
local drive before using easydd in those cases.

The disk is checked again before and after unmounting. Unmounting is never
forced. If it fails because a volume is busy, close the applications using it
and try again.

### Images

Accepts uncompressed raw `.img` and `.iso` files. The file must be readable,
regular, nonempty, and aligned to 512-byte sectors; it must also match the target
disk's sector alignment. Use the actual file path; file symlinks are refused.
Known compressed archives and DMG containers are
rejected, even when renamed to `.img`.

Raw images have no universal identifying header. Validation does not establish
that an image is bootable, authentic, or suitable for your hardware. Use a
trusted image and verify its published checksum before writing. Extract
compressed downloads first; `.dmg`, `.zip`, `.gz`, and `.xz` files are not raw
images.

### Progress and interruption

`pv` shows percentage, bytes transferred, speed, elapsed time, and ETA while
macOS `dd` writes to the raw device. Reaching 100% is followed by flushing and
ejection; wait for **Done** before disconnecting the target.

Keep the image unchanged and the disk connected throughout the operation.
Rechecking cannot lock the physical hardware against unplugging or replacement.

Press **Ctrl+C** to cancel. easydd waits for the writer to stop before returning
the terminal. A cancelled or failed write may leave the disk with an incomplete
image. It does not attempt to restore overwritten data. If ejection fails after
a completed write, eject the disk manually before disconnecting it.

## Tab completion

Bash completes filenames by default; no setup is required.
Homebrew installs `_easydd` for zsh, which completes `.img` and `.iso` filenames.
Start a new terminal after installation.

If zsh completion is not enabled, add this to `~/.zshrc`:

```zsh
fpath=("$(brew --prefix)/share/zsh/site-functions" $fpath)
autoload -Uz compinit
compinit
```

For Oh My Zsh, put the `fpath` line before `source "$ZSH/oh-my-zsh.sh"`;
Oh My Zsh loads `compinit` itself. In an existing terminal, generic filename
completion can be enabled with:

```zsh
compdef _files easydd
```

## From source

```sh
brew install python@3.13 pv
export PATH="$(brew --prefix python@3.13)/libexec/bin:$HOME/.local/bin:$PATH"
git clone https://github.com/VijitSingh97/easydd.git
cd easydd
git checkout v0.0.1
make install PREFIX="$HOME/.local"
```

Ensure `~/.local/bin` is on your PATH and `python3` is available. For zsh, put
`~/.local/share/zsh/site-functions` in `fpath` before loading `compinit`.

## Update or remove

```sh
brew update
brew upgrade vijitsingh97/easydd/easydd
brew uninstall vijitsingh97/easydd/easydd
```

For a source install, use `make uninstall PREFIX="$HOME/.local"` from the checkout.

## Development and testing

```sh
make check
make test
```

Python standard-library tests mock disk discovery, administrator authentication,
unmounting, progress processes, and `dd`. They exercise internal/startup/source
exclusion, multi-store APFS, invalid images, changed targets, cancellations, and
writer failures. CI runs on macOS 15 and the latest macOS runner. Manual CI runs
also smoke-test the public Homebrew installation.

**Tests never write to real disks or request sudo.** Mocked tests cannot validate
actual hardware behavior or media integrity. A real flash requires a separate,
explicit operator decision on a disposable external disk.

For a release, update `VERSION`, the version constant in `bin/easydd`, and
`CHANGELOG.md`; run the checks and push a matching `v<version>` tag. The release
workflow repeats the mocked safety tests before publishing. Update
`Formula/easydd.rb` with the tag URL and SHA-256 checksum for Homebrew.

## License

[MIT](LICENSE) © 2026 Vijit Singh.
