from pathlib import Path
from types import SimpleNamespace
import tempfile
import time
import unittest
from unittest.mock import patch

from fenlet.core import browser_window_context, build_actions, clutter_hints, guard_cleanup_decisions, local_decisions, frames_overlap, reconcile_actions
from fenlet.operations import apply, save_plan
from fenlet.runtime import browser_processes, inspect_browser_context, verify_browser_actions
from tests.test_core import inventory, window


def report(windows, **change):
    result = []
    for w in windows:
        b = w['bounds']
        result.append({'bounds': dict(left=b['x'], top=b['y'], width=b['width'], height=b['height'], windowState='normal'), 'empty': True, 'attached': False, 'tabs': 1, **change})
    return {'complete': True, 'windows': result}


class CleanupTest(unittest.TestCase):
    def setUp(self):
        self.windows = [window('blank-1', 'Google Chrome'), window('blank-2', 'Google Chrome')]

    def test_all_tabs_empty_and_unattached_with_exact_group_coverage(self):
        contexts = browser_window_context(self.windows, report(self.windows), 9333)
        self.assertEqual({v['kind'] for v in contexts.values()}, {'empty_unattached'})
        for w in self.windows: w['browser_context'] = contexts[w['id']]
        roles = {d['id']: d['role'] for d in local_decisions(inventory(self.windows))}
        self.assertEqual(set(roles.values()), {'close'})

    def test_one_useful_background_tab_prevents_closing_the_stack(self):
        for change in ({'empty': False, 'tabs': 3}, {'attached': True}):
            observed = report(self.windows)
            observed['windows'][0].update(change)
            contexts = browser_window_context(self.windows, observed, 9333)
            self.assertEqual({v['kind'] for v in contexts.values()}, {'protected' if change.get('attached') else 'background_unattached'})

    def test_incomplete_mismatched_or_malformed_metadata_never_proves_a_close(self):
        for observed in ({'complete': False, 'windows': report(self.windows)['windows']}, report(self.windows[:1]), {'complete': True, 'windows': [None]}, report(self.windows, tabs=True), report(self.windows, attached=None)):
            self.assertEqual({v['kind'] for v in browser_window_context(self.windows, observed, 9333).values()}, {'protected'})

    def test_new_tab_title_and_marketing_title_cannot_close_other_browser_tabs(self):
        for title in ('New Tab', 'Example marketing site'):
            w = {**self.windows[0], 'title': title}
            result = guard_cleanup_decisions(inventory([w]), [{'id': w['id'], 'role': 'close'}])
            self.assertEqual(result[0]['role'], 'minimize')

    def test_duplicate_desktop_folders_close_but_focused_folder_stays(self):
        folders = [{**window(str(i), 'Finder', focused=i == 0), 'title': 'Desktop'} for i in range(3)]
        roles = {d['id']: d['role'] for d in local_decisions(inventory(folders))}
        self.assertTrue(roles['0'].startswith('display_'))
        self.assertEqual([roles['1'], roles['2']], ['close', 'close'])
        single = inventory(folders[1:2])
        self.assertNotIn('1', clutter_hints(single))

    def test_keep_awake_terminal_is_minimized_and_never_auto_closed(self):
        w = {**window('awake', 'Ghostty'), 'title': 'caffeinate -di'}
        inv = inventory([w])
        self.assertEqual(local_decisions(inv)[0]['role'], 'minimize')
        self.assertEqual(guard_cleanup_decisions(inv, [{'id': 'awake', 'role': 'close'}])[0]['role'], 'minimize')

    def test_useful_unattached_browser_is_minimized_but_an_attached_one_is_fixed(self):
        observed = report(self.windows, empty=False, tabs=3)
        contexts = browser_window_context(self.windows, observed, 9333)
        for w in self.windows: w['browser_context'] = contexts[w['id']]
        self.assertEqual({d['role'] for d in local_decisions(inventory(self.windows))}, {'minimize'})
        actions = [{'kind': 'minimize', 'window': w} for w in self.windows]
        with patch('fenlet.runtime.native_json', return_value=observed): verify_browser_actions(actions, self.windows)
        with patch('fenlet.runtime.native_json', return_value=report(self.windows, attached=True)):
            with self.assertRaises(ValueError): verify_browser_actions(actions, self.windows)

    def test_protected_browser_is_an_obstacle_for_work_panes(self):
        fixed = {**window('automation', 'Google Chrome'), 'protected': True, 'bounds': dict(x=-1400, y=-450, width=1000, height=1000)}
        work = window('work', 'Rex Beta', focused=True)
        inv = inventory([fixed, work])
        actions = build_actions(inv, local_decisions(inv))
        self.assertEqual(len(actions), 1)
        self.assertFalse(frames_overlap(actions[0]['target'], fixed['bounds']))

    def test_draft_reflows_when_an_automation_window_becomes_protected(self):
        bot = {**window('automation', 'Google Chrome'), 'bounds': dict(x=-1400, y=-450, width=1000, height=1000)}
        work = window('work', 'Rex Beta', focused=True)
        inv = inventory([bot, work])
        before = {'inventory': inv, 'actions': build_actions(inv, [{'id':'automation','role':'close'},{'id':'work','role':'display_external'}])}
        current = {**inv, 'windows': [{**bot, 'protected': True}, work]}
        actions = reconcile_actions(before, current)
        self.assertEqual(len(actions), 1)
        self.assertFalse(frames_overlap(actions[0]['target'], bot['bounds']))

    def test_close_revalidates_the_whole_group_even_when_only_one_will_close(self):
        contexts = browser_window_context(self.windows, report(self.windows), 9333)
        for w in self.windows: w['browser_context'] = contexts[w['id']]
        actions = [{'kind': 'close', 'window': self.windows[0]}]
        with patch('fenlet.runtime.native_json', return_value=report(self.windows)):
            verify_browser_actions(actions, self.windows)
        with patch('fenlet.runtime.native_json', return_value=report(self.windows, attached=True)):
            with self.assertRaises(ValueError): verify_browser_actions(actions, self.windows)

    def test_browser_activity_after_preview_aborts_before_any_mutation_or_journal(self):
        contexts = browser_window_context(self.windows, report(self.windows), 9333)
        for w in self.windows: w['browser_context'] = contexts[w['id']]
        inv = {**inventory(self.windows), 'created_at': time.time(), 'scan_ms': 0, 'coverage': {'complete': True, 'errors': []}}
        with tempfile.TemporaryDirectory() as directory, patch('fenlet.operations.STATE', Path(directory)):
            path, _ = save_plan(inv, local_decisions(inv), 'Clean up', None)
            with patch('fenlet.runtime.native_json', return_value=report(self.windows, empty=False)), patch('fenlet.operations.native_window_batch') as mutation:
                with self.assertRaises(ValueError): apply(path)
            mutation.assert_not_called()
            self.assertFalse((Path(directory)/'runs').exists())


class ProcessContextTest(unittest.TestCase):
    def test_process_lookup_is_batched_cached_and_scoped_to_chrome(self):
        chrome = [{**window(str(i), 'Google Chrome'), 'bundle_id': 'com.google.Chrome'} for i in range(25)]
        observed = SimpleNamespace(stdout='100 /Applications/Google Chrome --remote-debugging-port=9333 --remote-debugging-pipe\n')
        with patch('fenlet.runtime._browser_processes', {}), patch('fenlet.runtime.subprocess.run', return_value=observed) as lookup:
            first = browser_processes(chrome)
            self.assertEqual(browser_processes(chrome), first)
            lookup.assert_called_once()
            self.assertEqual(first[100], {'controlled': True, 'port': 9333})
            browser_processes([{**chrome[0], 'process_instance': 'replacement'}])
            self.assertEqual(lookup.call_count, 2)

    def test_probe_failure_protects_windows_without_exposing_launch_arguments(self):
        windows = [window('automation', 'Google Chrome')]
        with patch('fenlet.runtime.browser_processes', return_value={100: {'controlled': True, 'port': None}}), patch('fenlet.runtime.native_json') as native:
            inspect_browser_context(windows)
        native.assert_not_called()
        self.assertTrue(windows[0]['protected'])
        self.assertEqual(windows[0]['browser_context'], {'kind': 'protected', 'port': None})
