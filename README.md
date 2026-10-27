# kubectl-vpn

Run ordinary `kubectl` commands through an isolated OpenVPN connection without changing your desktop's routes.

`kubectl-vpn` starts an OpenVPN container on demand and routes requests to one configured Kubernetes API through a local HTTP CONNECT proxy. The original `kubectl` still runs on your host: local manifests, stdin, terminals, and port-forward listeners stay local. Other Kubernetes contexts keep their normal routing.

```text
kubectl → localhost proxy → isolated OpenVPN tunnel → Kubernetes API
other applications → existing host network or VPN
```

## Requirements

- Linux with Docker Engine 28 or newer, permission to use Docker, and `/dev/net/tun`.
- Python 3.10 or newer, `kubectl`, and zsh.
- An HTTPS Kubernetes API on port 443.
- A self-contained OpenVPN UDP or TCP-client profile with inline certificates/keys and at least one public IPv4 endpoint.
- A VPN username and password.

The initial release supports one protected API hostname and one VPN profile. Hostname-based VPN endpoints, custom API ports, external certificate files, and interactive MFA are not supported. Profiles using additional OpenVPN options may need adaptation. The runtime profile imports a limited option set, omits external scripts and private-address remotes, and adds AES-256-CBC compatibility for older servers.

## Install

Clone this repository and select the Kubernetes context you want to protect:

```sh
git clone https://github.com/AryanHamedani/kubectl-vpn.git
cd kubectl-vpn
kubectl config use-context YOUR_CONTEXT
python3 install.py --profile /path/to/vpn.ovpn
```

The installer builds the container image, stores private configuration outside the checkout, and adds a managed function to `.zshrc` with a backup. The function takes precedence over PATH changes made by version managers. The original kubectl binary and kubeconfig are preserved.

Open a new terminal, then run:

```sh
kubectl get namespaces
```

The first protected API command prompts for VPN credentials locally. Credentials are saved in a mode-600 file inside a mode-700 directory for unattended reconnection. For scripts or commands that consume stdin, authenticate first:

```sh
kubectl-vpn login
```

If `~/.local/bin` is not on your PATH, invoke `~/.local/bin/kubectl-vpn login` directly. Normal `kubectl` works through the installed zsh function regardless.

## Use

```sh
kubectl get pods -A
kubectl exec -it POD -- sh
kubectl port-forward service/SERVICE 8080:80
kubectl apply -f ./manifest.yaml
```

These commands retain their usual Kubernetes semantics. The container stays running between commands and starts on demand after reboot. Select a different context with `kubectl config use-context`, or pass `--context`, `--kubeconfig`, `--cluster`, or `--server` per invocation. Only the installed HTTPS API hostname on port 443 uses this tunnel. Help, completion, and local configuration commands do not require a VPN.

```sh
kubectl-vpn status
kubectl-vpn logs
kubectl-vpn stop
kubectl-vpn start
kubectl-vpn login  # replace saved credentials and reconnect
```

## Networking and isolation

- OpenVPN changes routes inside the container's network namespace. The tool does not modify host routes or host firewall rules.
- The proxy is published only at `127.0.0.1:18080`. It accepts HTTP CONNECT only to the configured API hostname on port 443.
- Kubernetes TLS remains end to end. The container does not receive kubeconfig or Kubernetes credentials.
- Container egress permits VPN endpoint traffic using the profile’s UDP or TCP transport, tunnel traffic, and replies from the proxy. Proxy upstream sockets are additionally bound to `tun0`; IPv6 is disabled in the container.
- Protected invocations replace HTTP proxy environment variables and clear `NO_PROXY`. A conflicting kubeconfig `proxy-url` causes an error.
- If the VPN fails, protected API traffic has no direct fallback. The container uses `NET_ADMIN` and the TUN device, not host networking or Docker's privileged mode.
- DNS for the API uses `1.1.1.1` through the VPN. API hostnames requiring private DNS are not supported by this initial release.

An existing host VPN can carry the outer OpenVPN connection. Docker forwarding and VPN firewall behavior vary by machine; verify container egress on your system. This tool does not manage the host VPN or enforce that it is connected.

This integration covers ordinary `kubectl`, not independent clients such as IDEs or k9s. Invoking the original kubectl binary directly bypasses the wrapper. Other local processes/users can reach the restricted proxy, but still need Kubernetes credentials. Docker access itself is privileged; install only profiles you trust.

## Files and reuse

| Location | Contents |
| --- | --- |
| `~/.config/kubectl-vpn/` | Private runtime profile, credentials, endpoint list, settings |
| `~/.local/share/kubectl-vpn/` | Installed Python launcher |
| `~/.local/bin/kubectl` | Wrapper executable |
| `~/.local/bin/kubectl-vpn` | Lifecycle command |
| `~/.zshrc` | Managed function, with a timestamped backup |

The repository contains no VPN profiles, credentials, or kubeconfig. Each user supplies their own files locally. Re-run the installer to update the runtime code. After changing profiles, remove the existing managed container with `docker rm -f kubectl-vpn` before reconnecting.

Port `18080` must be available. The image is built locally as `kubectl-vpn:local`; no prebuilt image or hosted service is required.

## Uninstall

```sh
python3 install.py --uninstall
```

Open a new terminal afterward. This removes the wrapper integration and managed container. Private configuration is retained for reuse; remove `~/.config/kubectl-vpn` separately to erase it. You may also remove `~/.local/share/kubectl-vpn` and the `kubectl-vpn:local` image.

## Development and validation

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q vpnctl.py install.py container
docker build -t kubectl-vpn:local container
RUN_DOCKER_TESTS=1 python3 -m unittest discover -s tests -v
```

Tests cover configuration selection, argument handling, proxy restrictions, and container ownership checks. Live connectivity and streaming checks require your own VPN and Kubernetes environment:

```sh
kubectl get --raw=/version --request-timeout=15s
```

No live VPN or cluster is used in CI.

## License

MIT. See [LICENSE](LICENSE).
