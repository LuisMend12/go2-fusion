"""Mac-only regression checks using disposable credentials, never the real server.

Run on the Mac: python3 -m unittest discover -s docker/mac/tests -v
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


XAUTH = Path('/opt/X11/bin/xauth')
HELPER = Path(__file__).resolve().parents[1] / 'mac-xauth.sh'


@unittest.skipUnless(XAUTH.is_file(), 'Requires the XQuartz xauth tool on macOS')
class XQuartzCredentials(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='go2-auth-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'docker').mkdir()
        shutil.copyfile(HELPER, self.root / 'docker/mac-xauth.sh')
        fake_bin = self.root / 'bin'
        fake_bin.mkdir()
        fake_ps = fake_bin / 'ps'
        fake_ps.write_text('#!/bin/sh\ncat "$MOCK_XQUARTZ_PS"\n')
        fake_ps.chmod(0o755)
        self.processes = self.root / 'processes'
        self.processes.write_text('')
        self.stale = self.root / 'stale-auth'
        self.cookie(self.stale, ':0', '11' * 16)
        self.env = dict(os.environ, PATH=f'{fake_bin}:/usr/bin:/bin',
                        MOCK_XQUARTZ_PS=str(self.processes),
                        XAUTHORITY=str(self.stale),
                        GO2_MAC_XAUTH_DIR=str(self.root / "xauth"))

    def cookie(self, path, display, value):
        path.touch()
        subprocess.run([str(XAUTH), '-f', str(path), 'add', display,
                        'MIT-MAGIC-COOKIE-1', value], check=True, capture_output=True)

    def server(self, display, value):
        auth = self.root / f'server auth {display.lstrip(":")}'
        self.cookie(auth, display, value)
        self.processes.write_text(
            f'xinit /opt/X11/bin/Xquartz {display} -auth {auth}\n'
            f'/opt/X11/bin/Xquartz {display} -listen tcp -auth {auth} -nolisten local\n')

    def run_helper(self):
        return subprocess.run(['bash', str(self.root / 'docker/mac-xauth.sh')],
                              env=self.env, text=True, capture_output=True)

    def exported_cookie(self):
        return subprocess.check_output(
            [str(XAUTH), '-f', str(self.root / 'xauth/Xauthority'), 'nlist'],
            text=True).strip()

    def test_active_server_wins_over_stale_default_and_rotates(self):
        for display, value in [(':1', '22' * 16), (':2', '33' * 16)]:
            with self.subTest(display=display):
                self.server(display, value)
                result = self.run_helper()
                self.assertEqual(result.returncode, 0, result.stderr)
                record = self.exported_cookie()
                self.assertTrue(record.startswith('ffff '))
                self.assertTrue(record.endswith(value))
                self.assertNotIn(value, result.stdout + result.stderr)
                self.assertEqual((self.root / 'xauth/display').read_text(),
                                 f'host.docker.internal{display}\n')
                self.assertEqual((self.root / 'xauth/Xauthority').stat().st_mode & 0o777,
                                 0o600)

    def test_missing_or_empty_server_preserves_existing_export(self):
        self.server(':0', '44' * 16)
        self.assertEqual(self.run_helper().returncode, 0)
        before = self.exported_cookie()
        for process in ['', '/opt/X11/bin/Xquartz :0 -auth /does/not/exist\n']:
            self.processes.write_text(process)
            self.assertNotEqual(self.run_helper().returncode, 0)
            self.assertEqual(self.exported_cookie(), before)
        empty = self.root / 'empty-auth'
        empty.touch()
        self.processes.write_text(f'/opt/X11/bin/Xquartz :0 -auth {empty}\n')
        self.assertNotEqual(self.run_helper().returncode, 0)
        self.assertEqual(self.exported_cookie(), before)


if __name__ == '__main__':
    unittest.main()
