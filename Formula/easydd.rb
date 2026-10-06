class Easydd < Formula
  desc "Write raw images to external macOS disks with a progress bar"
  homepage "https://github.com/VijitSingh97/easydd"
  url "https://github.com/VijitSingh97/easydd/archive/refs/tags/v0.0.1.tar.gz"
  sha256 "c96c116380fe1ed4ad7d5f3537580673745e96201da3b3a99520b64f176563e3"
  license "MIT"

  depends_on "pv"
  depends_on "python@3.13"
  depends_on macos: :sonoma

  def install
    inreplace "bin/easydd", "#!/usr/bin/env python3",
              "#!#{Formula["python@3.13"].opt_bin}/python3.13"
    bin.install "bin/easydd"
    zsh_completion.install "completions/_easydd"
  end

  test do
    assert_match "easydd 0.0.1", shell_output("#{bin}/easydd --version")
    assert_match "Write a raw image", shell_output("#{bin}/easydd --help")
    (testpath/"invalid.txt").write "This is not a disk image."
    assert_match "Invalid file type", shell_output("#{bin}/easydd #{testpath}/invalid.txt 2>&1", 1)
  end
end
