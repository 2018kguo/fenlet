from pathlib import Path
import plistlib
import unittest
from unittest.mock import patch

from scripts.app_registration import BUNDLE_ID, LSREGISTER, forget, prefer_install, registered_fenlet_paths


class RegistrationTest(unittest.TestCase):
    def test_only_exact_bundle_identifiers_are_selected(self):
        dump = f"""bundle id: Fenlet (0x10)
path: /Applications/Fenlet.app (0x20)
identifier: {BUNDLE_ID}
    path: /private/unrelated.app
    identifier: unrelated
bundle id: Other app (0x11)
path: /Applications/Fenlet Companion.app (0x21)
identifier: {BUNDLE_ID}.other
bundle id: Old Fenlet (0x12)
path: /private/Test Folder/Fenlet.app (0x22)
identifier: {BUNDLE_ID}
"""
        self.assertEqual(registered_fenlet_paths(dump), [Path('/Applications/Fenlet.app'), Path('/private/Test Folder/Fenlet.app')])

    def test_missing_or_relative_paths_are_never_unregistered(self):
        for path in ('', 'relative/Fenlet.app'):
            self.assertEqual(registered_fenlet_paths(f'bundle id: Fenlet\nidentifier: {BUNDLE_ID}\npath: {path}'), [])

    def test_keep_installed_app_and_unregister_only_its_other_paths(self):
        keep, old, temporary = Path('/Applications/Fenlet.app'), Path('/tmp/Old Fenlet.app'), Path('/tmp/staging.noindex/Fenlet.app')
        dump = '\n'.join(f'bundle id: Fenlet\npath: {p}\nidentifier: {BUNDLE_ID}' for p in (keep, old))
        info = plistlib.dumps({'CFBundleIdentifier': BUNDLE_ID})
        with patch.object(Path, 'read_bytes', return_value=info), patch('scripts.app_registration.subprocess.check_output', return_value=dump), patch('scripts.app_registration.subprocess.run') as run:
            prefer_install(keep, temporary_paths=[temporary, keep])
        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(commands[-1], [LSREGISTER, '-f', str(keep.resolve())])
        self.assertEqual(commands[:-1], [[LSREGISTER, '-u', *map(str, sorted([old, temporary]))]])
        self.assertTrue(all(c[0] == LSREGISTER for c in commands))

    def test_wrong_preferred_app_cannot_change_any_registration(self):
        with patch.object(Path, 'read_bytes', return_value=plistlib.dumps({'CFBundleIdentifier': 'other.app'})), patch('scripts.app_registration.subprocess.run') as run, patch('scripts.app_registration.subprocess.check_output') as dump:
            with self.assertRaises(ValueError): prefer_install('/Applications/Other.app')
        run.assert_not_called(); dump.assert_not_called()

    def test_empty_forget_does_not_run_an_unscoped_command(self):
        with patch('scripts.app_registration.subprocess.run') as run: forget()
        run.assert_not_called()
