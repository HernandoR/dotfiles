#!/usr/bin/env bash

# Install command-line tools using Homebrew.

# Make sure we’re using the latest Homebrew.
brew update

# Upgrade any already-installed formulae.
brew upgrade

# Save Homebrew’s installed location.
BREW_PREFIX=$(brew --prefix)

# Install GNU core utilities (those that come with macOS are outdated).
# Don’t forget to add `$(brew --prefix coreutils)/libexec/gnubin` to `$PATH`.
brew install coreutils
ln -s "${BREW_PREFIX}/bin/gsha256sum" "${BREW_PREFIX}/bin/sha256sum"

# Install some other useful utilities like `sponge`.
brew install moreutils
# Install GNU `find`, `locate`, `updatedb`, and `xargs`, `g`-prefixed.
brew install findutils
# Install GNU `sed`, overwriting the built-in `sed`.
brew install gnu-sed # --with-default-names
# Install a modern version of Bash.
# brew install bash
# brew install bash-completion2

# # Switch to using brew-installed bash as default shell
# if ! fgrep -q "${BREW_PREFIX}/bin/bash" /etc/shells; then
#   echo "${BREW_PREFIX}/bin/bash" | sudo tee -a /etc/shells;
#   chsh -s "${BREW_PREFIX}/bin/bash";
# fi;

# Install `wget` with IRI support.
# brew install wget --with-iri
brew install wget

# Install GnuPG to enable PGP-signing commits.
# brew install gnupg

# Install more recent versions of some macOS tools.  -----------------------------------------------
brew install vim # --with-override-system-vi
brew install grep
brew install openssh

brew install xmake

# brew install screen
# brew install php
# brew install gmp


# # some terminal tools -----------------------------------------------
# Install tmux: Terminal multiplexer that allows multiple terminal sessions within a single window.
brew install tmux

# Install thefuck: Command-line tool for correcting mistyped or incorrect commands.
brew install thefuck

# Install tldr: Simplified and community-driven man pages (manual pages) for various commands.
brew install tldr

# Font install tool
curl -fsSL https://raw.githubusercontent.com/HernandoR/getnf/master/install.sh | sh

# Install casks
# Install Visual Studio Code: A popular source code editor and IDE.
brew install --cask visual-studio-code

# Install Microsoft Edge: Web browser developed by Microsoft.
brew install --cask microsoft-edge

# Install iTerm2: Terminal emulator for macOS with advanced features.
brew install --cask iterm2

# Install Termius: SSH client and Telnet client for remote access to servers.
brew install --cask termius

# Install Miniforge: Minimal distribution of the conda package manager and Python.
brew install --cask miniforge

# Install PyCharm Community Edition with Anaconda plugin: Integrated development environment for Python.
brew install --cask pycharm-ce-with-anaconda-plugin

# Install TexLive: Comprehensive TeX system for typesetting documents.
brew install --cask texlive

# Install QSpace Pro: Software for managing and organizing digital files.
brew install --cask qspace-pro

# Screen protect
brew install --cask fliqlo

# brew install --cask microsoft-office-businesspro
# brew install --cask microsoft-office
# brew install --cask wpsoffice
# brew install --cask wpsoffice-cn


# # Install font tools. -----------------------------------------------
# brew tap bramstein/webfonttools
# brew install sfnt2woff
# brew install sfnt2woff-zopfli
# brew install woff2

# # Install some CTF tools; see https://github.com/ctfs/write-ups. -----------------------------------------------

# # Install aircrack-ng: Tool for wireless network auditing and penetration testing.
# brew install aircrack-ng

# # Install bfg: Git repo cleaner and history simplifier.
# brew install bfg

# # Install binutils: Collection of binary tools, including object file utilities.
# brew install binutils

# # Install binwalk: Firmware analysis tool.
# brew install binwalk

# # Install cifer: Classical cipher tools.
# brew install cifer

# # Install dex2jar: Tools for converting Android .dex files to .jar files.
# brew install dex2jar

# # Install dns2tcp: Tool for tunneling TCP connections over DNS protocol.
# brew install dns2tcp

# # Install fcrackzip: Password cracking tool for zip archives.
# brew install fcrackzip

# # Install foremost: Forensics application to recover lost files.
# brew install foremost

# # Install hashpump: Tool for performing hash length extension attacks.
# brew install hashpump

# # Install hydra: Network login cracker.
# brew install hydra

# # Install john: Password cracker.
# brew install john

# # Install knock: Port-knock server and client.
# brew install knock

# # Install netpbm: Toolkit for manipulating graphic images.
# brew install netpbm

# # Install nmap: Network exploration and security auditing tool.
# brew install nmap

# # Install pngcheck: PNG image file analysis tool.
# brew install pngcheck

# # Install socat: Multipurpose relay for bidirectional data transfer.
# brew install socat

# # Install sqlmap: Automatic SQL injection and database takeover tool.
# brew install sqlmap

# # Install tcpflow: TCP/IP packet capture program.
# brew install tcpflow

# # Install tcpreplay: Tool for replaying network traffic.
# brew install tcpreplay

# # Install tcptrace: TCP dump file analysis tool.
# brew install tcptrace

# # Install ucspi-tcp: Tools for building TCP client-server applications.
# brew install ucspi-tcp

# # Install xpdf: PDF viewer and toolkit.
# brew install xpdf

# # Install xz: Compression utility.
# brew install xz

# Install other useful binaries. -----------------------------------------------

# Install ack: Tool for searching text files for patterns.
brew install ack

# Install git: Distributed version control system.
brew install git

# Install git-lfs: Git extension for versioning large files.
brew install git-lfs

# Install gs: Ghostscript, a PostScript and PDF interpreter.
brew install gs

# Install lua: Powerful, efficient, lightweight scripting language.
brew install lua

# Install lynx: Text-based web browser.
brew install lynx

# Install p7zip: Command-line file archiver with high compression ratio.
brew install p7zip

# Install pigz: Parallel implementation of gzip for faster compression.
brew install pigz

# Install pv: Pipe viewer for monitoring data progress.
brew install pv

# Install rename: Perl script for renaming multiple files.
brew install rename

# Install rlwrap: Readline wrapper for command-line tools.
brew install rlwrap

# Install ssh-copy-id: Tool for securely installing SSH keys on remote servers.
brew install ssh-copy-id

# Install tree: Display directory structure as a tree.
brew install tree

# Install vbindiff: Visual binary diff tool.
brew install vbindiff

# Install zopfli: Compression algorithm implementation.
brew install zopfli

# Remove outdated versions from the cellar.
brew cleanup


