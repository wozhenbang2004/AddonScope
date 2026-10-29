import json
import re
import tempfile
import unittest
from pathlib import Path

from addon_scope.models import Addon, Finding, ScanResult
from addon_scope.report import report_dict, write_html, write_json


class ReportTests(unittest.TestCase):
    def sample(self):
        root = str(Path.home() / 'private-client' / 'addons')
        return ScanResult(
            roots=[root],
            addons=[Addon('a', 'Example', root + '/a')],
            findings=[Finding('TEST', 'warning', 'Potential mismatch', 'Inspect ' + root + '/a', evidence=['From ' + root + '/a/vendor', str(Path.home() / 'other-file')])],
            loaded={'attrs': root + '/a/attrs/__init__.py'},
            environment={'nested': {'path': root + '/cache'}},
        )

    def test_redacts_nested_paths_and_evidence_without_mutating_scan(self):
        result = self.sample()
        redacted = report_dict(result)
        text = json.dumps(redacted)
        self.assertNotIn(str(Path.home()), text)
        self.assertNotIn('private-client', text)
        self.assertEqual(redacted['roots'], ['$SCAN_1'])
        self.assertEqual(redacted['loaded']['attrs'], '$SCAN_1/a/attrs/__init__.py')
        self.assertEqual(redacted['environment']['nested']['path'], '$SCAN_1/cache')
        self.assertIn('private-client', result.roots[0])
        self.assertTrue(redacted['paths_redacted'])

    def test_full_path_export_is_explicit(self):
        result = self.sample()
        data = report_dict(result, False)
        self.assertEqual(data['roots'], result.roots)
        self.assertFalse(data['paths_redacted'])

    def test_windows_path_variants_and_prefix_boundary(self):
        result = ScanResult(roots=[r'C:\Users\Pat\addons'])
        result.loaded = {'a': r'C:\Users\Pat\addons\a\x.py', 'b': 'C:/Users/Pat/addons/b/x.py', 'other': r'C:\Users\Pat\addons-extra\x.py'}
        data = report_dict(result)
        self.assertEqual(data['loaded']['a'], r'$SCAN_1\a\x.py')
        self.assertEqual(data['loaded']['b'], '$SCAN_1/b/x.py')
        self.assertEqual(data['loaded']['other'], result.loaded['other'])

    def test_root_slash_is_not_replaced_throughout_text(self):
        result = ScanResult(roots=['/'])
        result.findings = [Finding('A/B', 'info', 'A / B', 'ordinary / text')]
        data = report_dict(result)
        self.assertEqual(data['findings'][0]['title'], 'A / B')

    def test_html_escapes_script_termination_and_keeps_data_roundtrippable(self):
        result = self.sample()
        attack = '</script><img src=x onerror="alert(1)"><script>\u2028&'
        result.findings[0].title = attack
        with tempfile.TemporaryDirectory() as directory:
            path = write_html(result, Path(directory) / 'report.html')
            html = path.read_text(encoding='utf-8')
        self.assertNotIn(attack, html)
        embedded = re.search(r'<script type="application/json" id="report-data">(.*?)</script>', html, re.S).group(1)
        self.assertEqual(json.loads(embedded)['findings'][0]['title'], attack)
        self.assertNotIn('<', embedded)
        self.assertIn(".textContent=", html)
        self.assertNotIn('innerHTML', html)

    def test_empty_report_and_json_write(self):
        result = ScanResult(roots=[])
        with tempfile.TemporaryDirectory() as directory:
            html_path = write_html(result, Path(directory) / 'nested' / 'report.html')
            json_path = write_json(result, Path(directory) / 'nested' / 'report.json')
            self.assertIn('No findings in this scan', html_path.read_text(encoding='utf-8'))
            self.assertEqual(json.loads(json_path.read_text(encoding='utf-8'))['findings'], [])


if __name__ == '__main__':
    unittest.main()
