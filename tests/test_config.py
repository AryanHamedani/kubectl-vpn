import importlib.util
from pathlib import Path
import unittest
ROOT = Path(__file__).resolve().parents[1]
class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue((ROOT / 'vpnctl.py').exists(), 'VPN manager must exist')
        spec = importlib.util.spec_from_file_location('vpnctl', ROOT / 'vpnctl.py')
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
    def test_profile_keeps_keys_but_removes_host_scripts_and_private_remote(self):
        profile = 'client\nremote 10.0.0.1 1194\nremote 1.1.1.1 8443\nproto udp\nup /bad\nauth-user-pass old\n<key>\nSECRET\n</key>\n'
        result, remotes = self.module.prepare_profile(profile)
        self.assertIn('<key>\nSECRET\n</key>', result)
        self.assertNotIn('10.0.0.1', result)
        self.assertNotIn('/bad', result)
        self.assertNotIn('auth-user-pass old', result)
        self.assertIn('auth-user-pass /secrets/auth.txt', result)
        # nointeract would resend rejected credentials forever and can lock the account.
        self.assertIn('auth-retry none', result)
        self.assertEqual(remotes, [['1.1.1.1', 8443]])
    def test_unsupported_profile_fails_explicitly(self):
        with self.assertRaises(ValueError): self.module.prepare_profile('proto tcp-server\nremote 1.1.1.1 443\n')
    def test_tcp_client_profile_is_supported(self):
        result,remotes=self.module.prepare_profile('client\nproto tcp-client\nremote 1.1.1.1 443\n')
        self.assertIn('proto tcp-client',result)
        self.assertEqual(remotes,[['1.1.1.1',443]])

    def test_cluster_match_is_exact(self):
        self.assertTrue(self.module.protected_server('https://api.example:443', 'api.example'))
        self.assertFalse(self.module.protected_server('https://api.example.evil', 'api.example'))
        self.assertFalse(self.module.protected_server('https://other.example', 'api.example'))
    def test_proxy_environment_clears_bypass(self):
        env = self.module.proxy_environment({'NO_PROXY':'*', 'no_proxy':'api.example', 'HTTPS_PROXY':'bad'}, 18080)
        self.assertEqual(env['NO_PROXY'], '')
        self.assertEqual(env['no_proxy'], '')
        self.assertEqual(env['HTTPS_PROXY'], 'http://127.0.0.1:18080')
    def test_exec_remote_help_is_not_a_local_command(self):
        self.assertFalse(self.module.local_command(['exec','pod','--','program','--help']))
        self.assertTrue(self.module.local_command(['get','pods','--help']))

    def test_cluster_override_selects_protected_even_with_other_current_context(self):
        from unittest.mock import patch
        import json
        data={'current-context':'other','contexts':[{'name':'other','context':{'cluster':'other'}}],
              'clusters':[{'name':'other','cluster':{'server':'https://other.example'}},
                          {'name':'protected','cluster':{'server':'https://api.example'}}]}
        with patch.object(self.module.subprocess,'check_output',return_value=json.dumps(data)):
            self.assertEqual(self.module.selected_cluster('/bin/kubectl',['--cluster','protected','get','pods'])[0], 'https://api.example')

    def test_unmanaged_container_is_rejected(self):
        from unittest.mock import patch
        import subprocess, json
        response=subprocess.CompletedProcess([],0,json.dumps([{'Config':{'Labels':{}},'State':{'Running':True}}]))
        with patch.object(self.module.subprocess,'run',return_value=response):
            with self.assertRaises(RuntimeError): self.module.managed_container()

if __name__ == '__main__': unittest.main()
