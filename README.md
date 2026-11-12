# kubectl-vpn

Run ordinary `kubectl` commands through an isolated OpenVPN connection without changing your desktop's routes.

`kubectl-vpn` starts an OpenVPN container on demand and routes requests to one configured Kubernetes API through a local proxy. The container is [sidetunnel](https://github.com/AryanHamedani/sidetunnel), a general VPN-in-a-container proxy; this project adds the Kubernetes part: the `kubectl` wrapper, the kubeconfig integration and credential handling. The original `kubectl` still runs on your host: local manifests, stdin, terminals, and port-forward listeners stay local. Other Kubernetes contexts keep their normal routing.

```text
kubectl → localhost proxy → isolated OpenVPN tunnel → Kubernetes API
other applications → existing host network or VPN
```

## Requirements

- Linux with Docker Engine 28 or newer, permission to use Docker, and `/dev/net/tun`.
- Python 3.10 or newer, `kubectl`, and zsh.
- An HTTPS Kubernetes API on port 443.
- A self-contained OpenVPN UDP or TCP profile with inline certificates/keys.
- A VPN username and password.

One protected API hostname and one VPN profile are supported. Custom API ports, external certificate files, and interactive MFA are not. The container keeps a limited set of profile options and drops external scripts and routes; see [sidetunnel's profile notes](https://github.com/AryanHamedani/sidetunnel#the-profile).

## Install

Clone this repository and select the Kubernetes context you want to protect:

```sh
git clone https://github.com/AryanHamedani/kubectl-vpn.git
cd kubectl-vpn
kubectl config use-context YOUR_CONTEXT
python3 install.py --profile /path/to/vpn.ovpn
```

The installer pulls the pinned sidetunnel image, checks the profile, stores private configuration outside the checkout, and adds a managed function to `.zshrc` with a backup. The function takes precedence over PATH changes made by version managers. The original kubectl binary is preserved; the only kubeconfig change is a `proxy-url` on the protected cluster.

Open a new terminal, then run:

```sh
kubectl get namespaces
```

The first protected API command prompts for VPN credentials locally. Credentials are saved in a mode-600 file inside a mode-700 directory for unattended reconnection. For scripts or commands that consume stdin, authenticate first:

```sh
kubectl-vpn login
```

If `~/.local/bin` is not on your PATH, invoke `~/.local/bin/kubectl-vpn login` directly. Normal `kubectl` works through the installed zsh function regardless.

### Reaching other hosts through the same tunnel

To open an internal site in a browser through the tunnel, allow its hostname when installing. The flag is repeatable, and re-running the installer without `--profile` keeps the installed profile:

```sh
python3 install.py --allow-host intranet.example.com
```

Then point a proxy extension (for example FoxyProxy) at `127.0.0.1:18080`, type HTTP, for that site only. Allowed hosts are reachable on port 443. `--allow-host '*'` opens every host behind the VPN to anything on your machine that can reach the proxy; prefer a list. `--allow-host ''` clears the list. If the installer finds a running container it recreates it, which interrupts `kubectl` for a few seconds.

By default names are resolved by `1.1.1.1` through the VPN. Use `--dns vpn` for the resolvers the VPN pushes (needed for names that only exist inside the network), or `--dns ADDRESS` for a specific one.

## Use

```sh
kubectl get pods -A
kubectl exec -it POD -- sh
kubectl port-forward service/SERVICE 8080:80
kubectl apply -f ./manifest.yaml
```

These commands retain their usual Kubernetes semantics. The container stays running between commands. Docker restarts it after a crash or reboot (restart policy `unless-stopped`), and the wrapper starts it on demand otherwise. `kubectl-vpn stop` keeps it stopped until the next start. If the VPN rejects the saved credentials, the container stays up without retrying (repeated attempts can lock the account) and `kubectl` asks you to run `kubectl-vpn login`. Select a different context with `kubectl config use-context`, or pass `--context`, `--kubeconfig`, `--cluster`, or `--server` per invocation. Only the installed HTTPS API hostname on port 443 uses this tunnel. Help, completion, and local configuration commands do not require a VPN.

```sh
kubectl-vpn status
kubectl-vpn logs
kubectl-vpn stop
kubectl-vpn start
kubectl-vpn login  # replace saved credentials and reconnect
```

## Networking and isolation

- OpenVPN changes routes inside the container's network namespace. The tool does not modify host routes or host firewall rules.
- The proxy is published only at `127.0.0.1:18080`. It accepts connections (HTTP CONNECT or SOCKS5) only to the configured API hostname, plus any hosts added with `--allow-host`, on port 443.
- Kubernetes TLS remains end to end. The container does not receive kubeconfig or Kubernetes credentials.
- Container egress permits VPN endpoint traffic using the profile’s UDP or TCP transport, tunnel traffic, and replies from the proxy. Proxy upstream sockets are additionally bound to `tun0`; IPv6 is disabled in the container.
- The installer sets the protected cluster's kubeconfig `proxy-url` to `http://127.0.0.1:18080`, so every kubeconfig client uses the tunnel. Protected invocations also replace HTTP proxy environment variables and clear `NO_PROXY`. A different existing `proxy-url` causes an error.
- If the VPN fails, protected API traffic has no direct fallback. The container uses `NET_ADMIN` and the TUN device, not host networking or Docker's privileged mode.
- DNS queries go through the VPN, to `1.1.1.1` unless `--dns` says otherwise.

An existing host VPN can carry the outer OpenVPN connection. Docker forwarding and VPN firewall behavior vary by machine; verify container egress on your system. This tool does not manage the host VPN or enforce that it is connected.

Independent clients such as k9s, helm, and IDEs reach the API through the kubeconfig `proxy-url`. They do not start the container; if it is stopped, they fail with connection refused instead of connecting directly. Regenerating the kubeconfig drops `proxy-url`; re-run the installer to restore it. Other local processes/users can reach the restricted proxy, but still need Kubernetes credentials. Docker access itself is privileged; install only profiles you trust.

## Files and reuse

| Location | Contents |
| --- | --- |
| `~/.config/kubectl-vpn/` | Private profile, credentials, settings |
| `~/.local/share/kubectl-vpn/` | Installed Python launcher |
| `~/.local/bin/kubectl` | Wrapper executable |
| `~/.local/bin/kubectl-vpn` | Lifecycle command |
| `~/.zshrc` | Managed function, with a timestamped backup |
| kubeconfig | `proxy-url` on the protected cluster |

The repository contains no VPN profiles, credentials, or kubeconfig. Each user supplies their own files locally. Re-run the installer to update the runtime code, change the profile or change the allowed hosts; it recreates a running container.

Port `18080` must be available. The image is pulled from `ghcr.io/aryanhamedani/sidetunnel` at a version and digest pinned in `vpnctl.py`.

## Uninstall

```sh
python3 install.py --uninstall
```

Open a new terminal afterward. This removes the wrapper integration, the kubeconfig `proxy-url`, and the managed container. Private configuration is retained for reuse; remove `~/.config/kubectl-vpn` separately to erase it. You may also remove `~/.local/share/kubectl-vpn` and the sidetunnel image.

## Development and validation

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q vpnctl.py install.py
```

Tests cover configuration selection, argument handling, the container's options, and container ownership checks. The proxy, firewall and tunnel are tested in [sidetunnel](https://github.com/AryanHamedani/sidetunnel). Live connectivity and streaming checks require your own VPN and Kubernetes environment:

```sh
kubectl get --raw=/version --request-timeout=15s
```

No live VPN or cluster is used in CI.

## Security

See [SECURITY.md](SECURITY.md). Changes are listed in [CHANGELOG.md](CHANGELOG.md).

## License

MIT. See [LICENSE](LICENSE).
