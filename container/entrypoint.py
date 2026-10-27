import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

def rule(*args): subprocess.run(['iptables','-w',*args],check=True)
# All rules apply only inside this container's network namespace.
rule('-P','OUTPUT','DROP')
rule('-A','OUTPUT','-o','lo','-j','ACCEPT')
rule('-A','OUTPUT','-o','tun0','-j','ACCEPT')
rule('-A','OUTPUT','-o','eth0','-p','tcp','--sport','8080','-m','conntrack','--ctstate','ESTABLISHED','-j','ACCEPT')
for host,port in json.loads(Path('/secrets/remotes.json').read_text()):
    rule('-A','OUTPUT','-o','eth0','-p','udp','-d',host,'--dport',str(port),'-j','ACCEPT')
# Pin VPN endpoints to the original gateway; reconnects cannot recurse into tun0.
gateway=subprocess.check_output(['ip','-4','route','show','default'],text=True).split()[2]
for host,port in json.loads(Path('/secrets/remotes.json').read_text()):
    subprocess.run(['ip','route','replace',host+'/32','via',gateway,'dev','eth0'],check=True)
ready=Path('/tmp/vpn-ready')
ready.unlink(missing_ok=True)
Path('/tmp/up.sh').write_text('#!/bin/sh\ntouch /tmp/vpn-ready\n')
Path('/tmp/down.sh').write_text('#!/bin/sh\nrm -f /tmp/vpn-ready\n')
for file in ['up.sh','down.sh']: Path('/tmp/'+file).chmod(0o700)
vpn=subprocess.Popen(['openvpn','--config','/secrets/client.ovpn','--script-security','2',
                      '--up','/bin/sh /tmp/up.sh','--up-delay','--up-restart','--down','/bin/sh /tmp/down.sh','--down-pre'])
proxy=subprocess.Popen(['python3','/app/proxy.py'])
def stop(*_):
    ready.unlink(missing_ok=True)
    vpn.terminate(); proxy.terminate()
    sys.exit(0)
signal.signal(signal.SIGTERM,stop)
signal.signal(signal.SIGINT,stop)
while vpn.poll() is None and proxy.poll() is None: time.sleep(0.5)
stop()
