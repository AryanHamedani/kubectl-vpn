#!/usr/bin/env python3
"""Local lifecycle manager and transparent kubectl launcher."""
import fcntl
import getpass
import ipaddress
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import time
from urllib.parse import urlparse

CONFIG = Path(os.environ.get('KUBECTL_VPN_HOME', Path.home()/'.config/kubectl-vpn'))
NAME = 'kubectl-vpn'
IMAGE = 'kubectl-vpn:local'
PORT = 18080

def prepare_profile(source):
    result, remotes, block = [], [], None
    allowed = {'client','proto','persist-key','persist-tun','tls-client','remote-cert-tls',
               'auth','cipher','key-direction','tls-version-min','tls-cipher','remote-random'}
    for line in source.splitlines():
        s = line.strip()
        if block:
            result.append(line)
            if s == f'</{block}>': block = None
            continue
        if s.startswith('<'):
            tag = s[1:-1]
            if tag not in {'ca','cert','key','tls-auth','tls-crypt'}:
                raise ValueError(f'Unsupported inline block: {tag}')
            block = tag
            result.append(line)
            continue
        if not s or s.startswith(('#',';')): continue
        fields = shlex.split(s)
        if fields[0] == 'proto' and fields[1] not in {'udp', 'tcp-client'}:
            raise ValueError('This setup supports UDP or TCP-client OpenVPN profiles only.')
        if fields[0] == 'remote':
            addr = ipaddress.IPv4Address(fields[1])
            if not addr.is_global: continue
            port = int(fields[2]) if len(fields)>2 else 1194
            if not 1 <= port <= 65535: raise ValueError('Invalid remote port')
            remotes.append([str(addr), port])
            result.append(f'remote {addr} {port}')
        elif fields[0] in allowed: result.append(s)
    if block or not remotes: raise ValueError('Profile needs complete inline keys and a public IPv4 remote.')
    result.extend(['dev tun0','nobind','redirect-gateway def1','auth-user-pass /secrets/auth.txt',
                   'auth-nocache','auth-retry nointeract','connect-retry-max 2','server-poll-timeout 10',
                   'data-ciphers AES-256-GCM:AES-128-GCM:AES-256-CBC','data-ciphers-fallback AES-256-CBC',
                   'pull-filter ignore "dhcp-option"','pull-filter ignore "route-ipv6"',
                   'pull-filter ignore "ifconfig-ipv6"','verb 3'])
    return '\n'.join(result)+'\n', remotes

def protected_server(server, hostname):
    u = urlparse(server)
    return u.scheme == 'https' and u.hostname == hostname and (u.port or 443) == 443

def proxy_environment(original, port):
    env = original.copy()
    for key in ('HTTPS_PROXY','https_proxy','HTTP_PROXY','http_proxy'):
        env[key] = f'http://127.0.0.1:{port}'
    for key in ('NO_PROXY','no_proxy'): env[key] = ''
    return env

def run(args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)

def settings(): return json.loads((CONFIG/'settings.json').read_text())

def credentials():
    if not sys.stdin.isatty():
        raise RuntimeError('VPN credentials missing. Run kubectl-vpn login in a terminal.')
    user = input('VPN username: ').strip()
    password = getpass.getpass('VPN password: ')
    if not user or not password or '\n' in password: raise ValueError('Empty or invalid credentials')
    path = CONFIG/'auth.txt'
    fd = os.open(path, os.O_WRONLY|os.O_CREAT|os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd,'w') as f: f.write(user+'\n'+password+'\n')

def managed_container():
    probe=subprocess.run(['docker','inspect',NAME],capture_output=True,text=True)
    if probe.returncode:
        # Distinguish an absent container from an unavailable Docker daemon.
        run(['docker','info','--format','{{.ServerVersion}}'],stdout=subprocess.DEVNULL)
        return None
    obj=json.loads(probe.stdout)[0]
    if obj['Config'].get('Labels',{}).get('kubectl-vpn.managed')!='true':
        raise RuntimeError('Container name already belongs to another container; refusing to modify it')
    return obj

def remove_container():
    if managed_container(): run(['docker','rm','-f',NAME],stdout=subprocess.DEVNULL)

def start():
    cfg = settings()
    if not (CONFIG/'auth.txt').exists(): credentials()
    with (CONFIG/'start.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        obj = managed_container()
        if obj is None:
            run(['docker','run','-d','--name',NAME,'--restart','unless-stopped','--label','kubectl-vpn.managed=true',
                 '--cap-add=NET_ADMIN','--device=/dev/net/tun','--sysctl=net.ipv6.conf.all.disable_ipv6=1',
                 '--dns=1.1.1.1','--publish',f'127.0.0.1:{PORT}:8080',
                 '--mount',f'type=bind,src={CONFIG},dst=/secrets,readonly',
                 '--env',f'API_HOST={cfg["hostname"]}', '--read-only','--tmpfs','/tmp',
                 '--log-opt','max-size=2m','--log-opt','max-file=2',IMAGE], stdout=subprocess.DEVNULL)
        else:
            if not obj['State']['Running']: run(['docker','start',NAME], stdout=subprocess.DEVNULL)
        print('Waiting for VPN…', file=sys.stderr)
        for _ in range(60):
            state = subprocess.run(['docker','exec',NAME,'test','-f','/tmp/vpn-ready'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            if state.returncode == 0: return
            time.sleep(1)
        raise RuntimeError('VPN did not connect in 60 seconds. Run kubectl-vpn logs. No direct Kubernetes fallback was used.')

def selected_cluster(real, args):
    overrides={}
    i=0
    while i<len(args):
        arg=args[i]
        if arg=='--': break
        key=arg.split('=',1)[0]
        if key in {'--context','--kubeconfig','--cluster','--user','--server','-s'}:
            if '=' in arg: value=arg.split('=',1)[1]
            else:
                i+=1
                if i==len(args): raise ValueError(f'Missing value for {key}')
                value=args[i]
            overrides['--server' if key=='-s' else key]=value
        elif arg.startswith('-s') and not arg.startswith('--') and len(arg)>2:
            overrides['--server']=arg[2:]
        i+=1
    flags=['--kubeconfig',overrides['--kubeconfig']] if '--kubeconfig' in overrides else []
    data=json.loads(subprocess.check_output([real,'config','view','-o','json',*flags]))
    context_name=overrides.get('--context',data.get('current-context'))
    context=next((c['context'] for c in data.get('contexts',[]) if c['name']==context_name),{})
    cluster_name=overrides.get('--cluster',context.get('cluster'))
    cluster=next((c['cluster'] for c in data.get('clusters',[]) if c['name']==cluster_name),{})
    return overrides.get('--server',cluster.get('server','')),cluster.get('proxy-url')

def local_command(args):
    flags=args[:args.index('--')] if '--' in args else args
    return not args or args[0] in {'config','completion','help'} or '--help' in flags or '-h' in flags or (args[0]=='version' and '--client' in flags)


def kubectl(args):
    cfg=settings()
    real=cfg['kubectl']
    # Purely local commands never need a VPN or credentials.
    if local_command(args):
        os.execv(real,[real,*args])
    server, proxy=selected_cluster(real,args)
    if protected_server(server,cfg['hostname']):
        if proxy and proxy!=f'http://127.0.0.1:{PORT}':
            raise RuntimeError('Protected kubeconfig has a conflicting proxy-url; remove it before using this wrapper.')
        start()
        os.execve(real,[real,*args],proxy_environment(os.environ,PORT))
    os.execv(real,[real,*args])

def main():
    action=sys.argv[1] if len(sys.argv)>1 else 'status'
    if action=='kubectl': kubectl(sys.argv[2:])
    elif action=='login':
        credentials()
        remove_container()
        start()
    elif action=='start': start()
    elif action=='stop':
        if managed_container(): run(['docker','stop',NAME])
    elif action=='status': run(['docker','ps','-a','--filter',f'name=^{NAME}$'])
    elif action=='logs': run(['docker','logs','--tail','60',NAME])
    else: raise ValueError('Usage: kubectl-vpn {login|start|stop|status|logs}')

if __name__=='__main__':
    try: main()
    except (OSError,ValueError,RuntimeError,subprocess.CalledProcessError) as e:
        print(f'kubectl-vpn: {e}',file=sys.stderr)
        sys.exit(1)
