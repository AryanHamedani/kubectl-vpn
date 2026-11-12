#!/usr/bin/env python3
"""Local lifecycle manager and transparent kubectl launcher."""
import fcntl
import getpass
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import urlparse

CONFIG = Path(os.environ.get('KUBECTL_VPN_HOME', Path.home()/'.config/kubectl-vpn'))
NAME = 'kubectl-vpn'
# The proxy core, pinned by digest because a tag can be re-pointed. Bump together with the changelog.
IMAGE = 'ghcr.io/aryanhamedani/sidetunnel:0.1.0@sha256:d6c306c40edce10958ae8770f908d42127d5d2a078122ad5b50603c4e2a05ff1'
PORT = 18080

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

def run_command(cfg):
    command=['docker','run','-d','--name',NAME,'--restart','unless-stopped','--label','kubectl-vpn.managed=true',
             '--cap-add=NET_ADMIN','--device=/dev/net/tun','--sysctl=net.ipv6.conf.all.disable_ipv6=1',
             '--publish',f'127.0.0.1:{PORT}:8080','--mount',f'type=bind,src={CONFIG},dst=/config,readonly',
             '--env','ALLOWED_HOSTS='+','.join([cfg['hostname'],*cfg.get('allowed_hosts',[])]),'--env','ALLOWED_PORTS=443',
             '--read-only','--tmpfs','/tmp','--log-opt','max-size=2m','--log-opt','max-file=2']
    # Without this the core uses the resolvers pushed by the VPN.
    if cfg.get('dns'): command+=['--env','DNS_SERVERS='+cfg['dns']]
    return [*command,IMAGE]

def start():
    cfg = settings()
    if not (CONFIG/'auth.txt').exists(): credentials()
    with (CONFIG/'start.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        obj = managed_container()
        if obj is None: run(run_command(cfg), stdout=subprocess.DEVNULL)
        elif not obj['State']['Running']: run(['docker','start',NAME], stdout=subprocess.DEVNULL)
        print('Waiting for VPN…', file=sys.stderr)
        for _ in range(60):
            # The image's status command exits 0 when ready and 2 when the VPN rejected the credentials.
            state = subprocess.run(['docker','exec',NAME,'status'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode
            if state == 0: return
            if state == 2: raise RuntimeError('VPN rejected the saved credentials. Run kubectl-vpn login.')
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
