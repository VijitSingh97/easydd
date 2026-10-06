class Easydd < Formula
  desc "Write raw images to external macOS disks with a progress bar"
  homepage "https://github.com/VijitSingh97/easydd"
  url "https://github.com/VijitSingh97/easydd/archive/refs/tags/v0.0.2.tar.gz"
  sha256 "9cb352a107d7b6f9c1b57b0943ae77c51aa531d12c4022a73e2f61eb866adc42"
  license "MIT"

  depends_on macos: :sonoma
  depends_on "pv"
  depends_on "python@3.13"

  def install
    inreplace "bin/easydd", "#!/usr/bin/env python3",
              "#!#{formula_opt_bin("python@3.13")}/python3.13"
    bin.install "bin/easydd"
    zsh_completion.install "completions/_easydd"
  end

  test do
    assert_match "easydd 0.0.2", shell_output("#{bin}/easydd --version")
    assert_match "Write a raw image", shell_output("#{bin}/easydd --help")
    (testpath/"invalid.txt").write "This is not a disk image."
    assert_match "Invalid file type", shell_output("#{bin}/easydd #{testpath}/invalid.txt 2>&1", 1)
  end
end
