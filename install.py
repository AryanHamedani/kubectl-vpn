#!/usr/bin/env python3
"""Install or remove this user's reusable kubectl VPN integration."""
import argparse
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import time
from urllib.parse import urlparse
import vpnctl

ROOT=Path(__file__).resolve().parent
BEGIN='# >>> kubectl-vpn >>>'
END='# <<< kubectl-vpn <<<'

def update_rc(path, block):
    text=path.read_text() if path.exists() else ''
    if BEGIN in text:
        before, tail=text.split(BEGIN,1)
        _, after=tail.split(END,1)
        text=before.rstrip()+'\n'+after.lstrip('\n')
    if block: text=text.rstrip()+'\n\n'+BEGIN+'\n'+block+'\n'+END+'\n'
    if path.exists(): shutil.copy2(path,str(path)+f'.backup-{time.time_ns()}')
    path.write_text(text)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--profile',type=Path)
    parser.add_argument('--uninstall',action='store_true')
    args=parser.parse_args()
    home=Path.home()
    dest=home/'.local/share/kubectl-vpn'
    bindir=home/'.local/bin'
    rc=home/'.zshrc'
    if args.uninstall:
        update_rc(rc,'')
        for name in ['kubectl','kubectl-vpn']:
            p=bindir/name
            if p.exists() and 'kubectl-vpn' in p.read_text(): p.unlink()
        settings=vpnctl.CONFIG/'settings.json'
        if settings.exists():
            cfg=json.loads(settings.read_text())
            # Installs before kubeconfig integration recorded no cluster.
            if 'cluster' in cfg: subprocess.run([cfg['kubectl'],'config','set-cluster',cfg['cluster'],'--proxy-url='],check=True)
        vpnctl.remove_container()
        print('Shell integration removed. Open a new shell. Private profile and credentials retained in '+str(vpnctl.CONFIG))
        return
    if not args.profile: parser.error('--profile is required')
    existing=vpnctl.CONFIG/'settings.json'
    if existing.exists(): real=json.loads(existing.read_text())['kubectl']
    else:
        real=shutil.which('kubectl')
        if not real: raise RuntimeError('Install kubectl first')
    data=json.loads(subprocess.check_output([real,'config','view','--minify','-o','json']))
    cluster_name=data['clusters'][0]['name']
    cluster=data['clusters'][0]['cluster']
    parsed=urlparse(cluster['server'])
    if parsed.scheme!='https' or (parsed.port or 443)!=443: raise RuntimeError('Expected an HTTPS Kubernetes API on port 443')
    proxy_url=f'http://127.0.0.1:{vpnctl.PORT}'
    if cluster.get('proxy-url') not in (None,proxy_url): raise RuntimeError('Remove existing protected cluster proxy-url before installing')
    profile,remotes=vpnctl.prepare_profile(args.profile.read_text())
    for name in ['kubectl','kubectl-vpn']:
        p=bindir/name
        if p.exists() and 'kubectl-vpn' not in p.read_text():
            raise RuntimeError(f'Refusing to replace existing {p}')
    subprocess.run(['docker','build','-t',vpnctl.IMAGE,str(ROOT/'container')],check=True)
    vpnctl.CONFIG.mkdir(mode=0o700,parents=True,exist_ok=True)
    vpnctl.CONFIG.chmod(0o700)
    for name,content in [('client.ovpn',profile),('remotes.json',json.dumps(remotes)),
                         ('settings.json',json.dumps({'hostname':parsed.hostname,'kubectl':real,'cluster':cluster_name},indent=2))]:
        p=vpnctl.CONFIG/name
        fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
        os.fchmod(fd,0o600)
        with os.fdopen(fd,'w') as f:f.write(content)
    # Every kubeconfig client (k9s, helm, IDEs) then uses the tunnel, not only the wrapper.
    subprocess.run([real,'config','set-cluster',cluster_name,'--proxy-url='+proxy_url],check=True)
    dest.mkdir(parents=True,exist_ok=True)
    shutil.copy2(ROOT/'vpnctl.py',dest/'vpnctl.py')
    bindir.mkdir(parents=True,exist_ok=True)
    for name,argument in [('kubectl','kubectl '),('kubectl-vpn','')]:
        p=bindir/name
        p.write_text('#!/bin/sh\n# kubectl-vpn managed launcher\nexec python3 '+shlex.quote(str(dest/'vpnctl.py'))+' '+argument+'"$@"\n')
        p.chmod(0o755)
    update_rc(rc,'# A function takes precedence over mise activation and existing PATH order.\n'
              'unalias kubectl 2>/dev/null || true\n'
              'kubectl() { '+shlex.quote(str(bindir/'kubectl'))+' "$@"; }')
    print('Installed. Open a new terminal, then run kubectl get namespaces.')
    print('The first protected API command prompts locally for VPN credentials.')
    print('To authenticate explicitly: '+str(bindir/'kubectl-vpn')+' login')
if __name__=='__main__':main()
