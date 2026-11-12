# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-11-13

### Changed

- The container is now [sidetunnel](https://github.com/AryanHamedani/sidetunnel) 0.1.0, pulled from GHCR at a pinned version instead of built locally. The proxy, firewall and profile hardening moved there.
- Re-running the installer recreates a running container, so new settings apply immediately. `--profile` is optional when a profile is already installed.
- The profile is stored as given and hardened inside the container at start. Host names in `remote` and `proto tcp` profiles now work.

### Added

- `install.py --allow-host HOST` (repeatable) lets other hosts be reached through the same tunnel on port 443, for example from a browser.
- `install.py --dns` chooses the resolver used inside the tunnel, including the ones the VPN pushes.
- The proxy also speaks SOCKS5 on the same port.

### Upgrading

Re-run `python3 install.py` from the new checkout. The old `kubectl-vpn:local` image and `~/.config/kubectl-vpn/remotes.json` are no longer used and can be deleted.

## 0.1.0 - 2026-10-27 (untagged)

Initial version: `kubectl` wrapper, kubeconfig `proxy-url` integration, on-demand OpenVPN container with a single-host HTTP CONNECT proxy.

[0.2.0]: https://github.com/AryanHamedani/kubectl-vpn/releases/tag/v0.2.0
