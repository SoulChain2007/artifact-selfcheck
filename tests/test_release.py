"""Release mutation tests and sandboxed Windows installation integration."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('release', ROOT/'scripts/release.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path.cwd(), prefix='release-test-')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base/'skill'
        shutil.copytree(ROOT, self.root, ignore=shutil.ignore_patterns('__pycache__', '.git', 'release-test-*', 'selfcheck-*'))
        (self.root/release.MANIFEST).write_text(json.dumps(release.inventory(self.root)), encoding='utf-8')

    def test_inventory_rejects_missing_changed_and_extra(self):
        target = self.root/'VERSION'
        original = target.read_bytes()
        target.unlink()
        with self.assertRaises(OSError): release.verify(self.root)
        target.write_bytes(original)
        target = self.root/'README.md'
        original = target.read_bytes()
        target.write_bytes(original+b'altered')
        with self.assertRaisesRegex(ValueError, 'changed='): release.verify(self.root)
        target.write_bytes(original)
        (self.root/'unexpected.txt').write_text('extra')
        with self.assertRaisesRegex(ValueError, 'added='): release.verify(self.root)

    def test_reproducible_zip_and_root_layout(self):
        a,b = self.base/'a.zip',self.base/'b.zip'
        self.assertEqual(release.build(self.root,a)['sha256'],release.build(self.root,b)['sha256'])
        with zipfile.ZipFile(a) as z:
            self.assertIn('SKILL.md', z.namelist())
            self.assertIn('LICENSE', z.namelist())
            self.assertFalse(any('__pycache__' in n or '_bak_' in n for n in z.namelist()))
        with self.assertRaisesRegex(ValueError, 'outside'): release.build(self.root,self.root/'bad.zip')

    def install(self, archive):
        engine = shutil.which('powershell')
        if not engine: self.skipTest('Windows PowerShell unavailable')
        return subprocess.run([engine,'-NoProfile','-ExecutionPolicy','Bypass','-File',str(self.root/'scripts/install_windows.ps1'),
                               '-Archive',str(archive),'-ProfileRoot',str(self.base/'profile'),'-DesktopPath',str(self.base/'desktop')],
                              capture_output=True,encoding='utf-8',errors='replace',timeout=60)

    def test_installer_three_hosts_backup_and_desktop(self):
        old = self.base/'profile/.codex/skills/artifact-selfcheck'
        old.mkdir(parents=True)
        (old/'OLD').write_text('preserve me')
        archive = self.base/'skill.zip'
        release.build(self.root,archive)
        result = self.install(archive)
        self.assertEqual(0,result.returncode,result.stdout+result.stderr)
        for host in ('.codex','.workbuddy','.workbuddy-ai'):
            release.verify(self.base/f'profile/{host}/skills/artifact-selfcheck')
        self.assertEqual(archive.read_bytes(),(self.base/'desktop/artifact-selfcheck-3.0.2-skillhub.zip').read_bytes())
        self.assertEqual(1,len(list((self.base/'profile/artifact-selfcheck-backups').glob('*/OLD'))))
        report=json.loads((self.base/'desktop/artifact-selfcheck-3.0.2-sync.json').read_text(encoding='utf-8-sig'))
        self.assertEqual(3,len(report['installations']))

    def test_installer_rejects_tampering_before_writes(self):
        archive=self.base/'bad.zip'
        release.build(self.root,archive)
        with zipfile.ZipFile(archive,'a') as z: z.writestr('injected.txt','unexpected')
        result=self.install(archive)
        self.assertNotEqual(0,result.returncode,result.stdout+result.stderr)
        self.assertIn('Payload file set differs',result.stderr)
        self.assertFalse((self.base/'profile').exists())

    def test_installer_rejects_traversal_before_writes(self):
        archive=self.base/'traversal.zip'
        with zipfile.ZipFile(archive,'w') as z: z.writestr('../escaped.txt','bad')
        result=self.install(archive)
        self.assertNotEqual(0,result.returncode)
        self.assertIn('Unsafe',result.stderr)
        self.assertFalse((self.base/'profile').exists())

    def test_preflight_preserves_old_copies_and_replaces_stale_report(self):
        old = self.base/'profile/.codex/skills/artifact-selfcheck'
        old.mkdir(parents=True)
        (old/'OLD').write_text('old')
        blocked = self.base/'profile/.workbuddy/skills'
        blocked.parent.mkdir(parents=True)
        blocked.write_text('not a directory')
        desktop = self.base/'desktop'
        desktop.mkdir()
        report = desktop/'artifact-selfcheck-3.0.2-sync.json'
        report.write_text('{"status":"success","stale":true}')
        archive = self.base/'skill.zip'
        release.build(self.root,archive)
        result = self.install(archive)
        self.assertNotEqual(0,result.returncode)
        self.assertIn('Target is not a directory',result.stderr)
        self.assertEqual('old',(old/'OLD').read_text())
        failure = json.loads(report.read_text(encoding='utf-8-sig'))
        self.assertEqual('failed',failure['status'])
        self.assertEqual([],failure['installations'])


if __name__ == '__main__': unittest.main()
