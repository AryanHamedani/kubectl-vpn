"""Optional Docker regression test; never uses a real VPN or credentials."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

@unittest.skipUnless(os.environ.get('RUN_DOCKER_TESTS') == '1', 'Set RUN_DOCKER_TESTS=1 to run Docker integration checks')
class ContainerHookTests(unittest.TestCase):
    def test_connection_hooks_work_on_noexec_tmpfs(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'client.ovpn').write_text('proto tcp-client\n')
            (root/'remotes.json').write_text('[["203.0.113.1",1194]]')
            stub=root/'openvpn'
            stub.write_text('''#!/usr/bin/python3
import pathlib, shlex, subprocess, sys
args=sys.argv
rules=subprocess.check_output(['iptables','-S','OUTPUT'],text=True)
assert '-p tcp' in next(line for line in rules.splitlines() if '203.0.113.1' in line)
subprocess.run(shlex.split(args[args.index('--up')+1]),check=True)
assert pathlib.Path('/tmp/vpn-ready').exists()
subprocess.run(shlex.split(args[args.index('--down')+1]),check=True)
assert not pathlib.Path('/tmp/vpn-ready').exists()
print('HOOKS_OK',flush=True)
''')
            stub.chmod(0o755)
            result=subprocess.run(['docker','run','--rm','--cap-add=NET_ADMIN','--read-only',
                '--tmpfs','/tmp:noexec','--mount',f'type=bind,src={root},dst=/secrets,readonly',
                '--mount',f'type=bind,src={stub},dst=/usr/sbin/openvpn,readonly',
                '--env','API_HOST=api.example',os.environ.get('VPN_TEST_IMAGE','kubectl-vpn:local')],
                capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('HOOKS_OK',result.stdout,result.stdout+result.stderr)
