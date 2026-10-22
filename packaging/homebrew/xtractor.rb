# Formula template for the Homebrew tap (<owner>/homebrew-xtractor, Formula/xtractor.rb).
# Fill in version, sha256 and the repository with packaging/homebrew/update_formula.sh.
class Xtractor < Formula
  desc "Extract the audio or video track from a YouTube video"
  homepage "https://github.com/BelongaGezza/Xtractor"
  version "0.0.0"
  url "https://github.com/BelongaGezza/Xtractor/releases/download/v#{version}/Xtractor-#{version}-macos-arm64.tar.gz"
  sha256 "0000000000000000000000000000000000000000000000000000000000000000"
  license "MIT"

  depends_on arch: :arm64
  depends_on :macos

  def install
    bin.install "Xtractor"
  end

  test do
    assert_match version.to_s, shell_output("#{bin}/Xtractor --version")
  end
end
