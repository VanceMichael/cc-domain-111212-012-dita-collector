import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import app
from collector import (Collection, DirectoryPackage, MemoryPackage,
                       build_view, normalize_rel)
from sampledata import product_package


class ProductViewTests(unittest.TestCase):
    def setUp(self):
        self.package = MemoryPackage(product_package())
        self.collection = Collection(self.package)
        self.alpha = self.collection.add_view(
            'maps/alpha-product.map', {'product': 'alpha'})
        self.beta = self.collection.add_view(
            'maps/beta-product.map', {'product': 'beta'})

    def test_views_are_ordered_and_conditionally_filtered(self):
        alpha_hrefs = [entry['href'] for entry in self.alpha['entries']]
        beta_hrefs = [entry['href'] for entry in self.beta['entries']]
        self.assertEqual(alpha_hrefs,
                         ['topics/guide.dita', 'topics/service-a.dita'])
        self.assertEqual(beta_hrefs,
                         ['topics/guide.dita', 'topics/service-b.dita'])
        # 过滤条件作用于实际展开路径并留下可审计记录
        rejected = {(item['rejected_attribute'].get('product'),
                     item['expansion_path'][-1]['href'])
                    for item in self.alpha['filtered_out']}
        self.assertIn(('beta', '../topics/service-b.dita'), rejected)
        self.assertTrue(any(item['rejected_attribute'].get('audience') == 'service'
                            for item in self.alpha['filtered_out']))
        # 被剪分支上的旧机型步骤不进入新机型条目
        self.assertFalse(any('service-b' in href for href in alpha_hrefs))

    def test_same_key_resolves_differently_per_view(self):
        def support_href(view):
            guide = next(e for e in view['entries']
                         if e['href'].endswith('guide.dita'))
            segment = next(s for paragraph in guide['paragraphs']
                           for s in paragraph['segments']
                           if s.get('keyref') == 'support')
            return segment
        self.assertEqual(support_href(self.alpha)['resolved_href'],
                         'topics/alpha-support.dita')
        self.assertEqual(support_href(self.beta)['resolved_href'],
                         'topics/beta-support.dita')
        self.assertNotEqual(self.alpha['view_id'], self.beta['view_id'])

    def test_resource_only_provides_resources_but_no_reading_entries(self):
        for view in (self.alpha, self.beta):
            entry_hrefs = {entry['href'] for entry in view['entries']}
            self.assertNotIn('topics/common-notes.dita', entry_hrefs)
            self.assertIn('topics/common-notes.dita', view['resources'])
            # resource-only 分支登记的键仍可被 keyref 使用
            self.assertIn('policy', {row['key'] for row in view['keys']})

    def test_file_path_is_not_unique_entry_identity(self):
        guide_entries = []
        for view in self.collection.views:
            entry = next(e for e in view['entries']
                         if e['href'] == 'topics/guide.dita')
            guide_entries.append(entry['entry_id'])
        self.assertNotEqual(guide_entries[0], guide_entries[1])
        # 展开路径携带 keyscope/条件上下文
        guide = next(e for e in self.alpha['entries']
                     if e['href'] == 'topics/guide.dita')
        self.assertTrue(guide['expansion_path'])
        self.assertEqual(guide['expansion_path'][0]['file'],
                         'maps/alpha-product.map')

    def test_conref_keeps_source_chain_and_supports_ranges(self):
        alpha_guide = next(e for e in self.alpha['entries']
                           if e['href'].endswith('guide.dita'))
        reused = alpha_guide['paragraphs'][2]
        self.assertEqual([loc['file'] for loc in reused['source_chain']],
                         ['topics/guide.dita', 'topics/common-notes.dita'])
        self.assertEqual(reused['source_chain'][-1]['element'], 'safety')
        beta_service = next(e for e in self.beta['entries']
                            if e['href'].endswith('service-b.dita'))
        range_sources = [p['source_chain'][-1]['element']
                         for p in beta_service['paragraphs'][1:]]
        self.assertEqual(range_sources, ['range-start', 'range-mid', 'range-end'])

    def test_provenance_lists_both_chain_and_final_location(self):
        result = self.collection.provenance(
            'topics/common-notes.dita', 'safety')
        locations = {(item['root_map'], item['entry_href'],
                      item['paragraph_order']) for item in result['occurrences']}
        self.assertIn(('maps/alpha-product.map', 'topics/guide.dita', 2), locations)
        self.assertIn(('maps/alpha-product.map', 'topics/service-a.dita', 1), locations)
        self.assertIn(('maps/beta-product.map', 'topics/guide.dita', 2), locations)
        for item in result['occurrences']:
            self.assertEqual(item['source_chain'][0]['file'], item['entry_href'])

    def test_impact_scopes_recollection_to_affected_views(self):
        shared = self.collection.impact('topics/common-notes.dita')
        self.assertEqual(len(shared['affected_views']), 2)
        for view in shared['affected_views']:
            self.assertIn('conref-source', view['reasons'])
            self.assertTrue(view['entries'])
        alpha_only = self.collection.impact('topics/alpha-support.dita')
        self.assertEqual([v['root_map'] for v in alpha_only['affected_views']],
                         ['maps/alpha-product.map'])
        self.assertEqual([v['root_map'] for v in alpha_only['unaffected_views']],
                         ['maps/beta-product.map'])

    def test_reference_tags_are_never_body_text(self):
        guide = next(e for e in self.alpha['entries']
                     if e['href'].endswith('guide.dita'))
        for paragraph in guide['paragraphs']:
            for segment in paragraph['segments']:
                if segment['type'] == 'text':
                    self.assertNotIn('keyref', segment['text'])
                    self.assertNotIn('<xref', segment['text'])

    def test_diagnostics_for_missing_key_cycle_boundary_and_malformed(self):
        files = dict(product_package())
        files['maps/diag.map'] = (
            '<map id="diag"><topicref href="../topics/missing-key.dita"/>'
            '<topicref href="cycle-a.map"/>'
            '<topicref href="../topics/cross-boundary.dita"/>'
            '<topicref href="../topics/malformed-conref.dita"/></map>').encode()
        view = build_view(MemoryPackage(files), 'maps/diag.map', {})
        codes = {item['code'] for item in view['diagnostics']}
        self.assertEqual(
            codes,
            {'unresolved-key', 'reference-cycle',
             'unsupported-boundary', 'malformed-conref'})
        for item in view['diagnostics']:
            self.assertTrue(item['expansion_path'])

    def test_keyscope_shadowing_nearest_scope_wins(self):
        files = {
            'm.map': (
                '<map><topicref keys="k" href="global.dita" processing-role="resource-only"/>'
                '<topicref href="a.dita"/>'
                '<topicref keyscope="scoped">'
                '<topicref keys="k" href="local.dita" processing-role="resource-only"/>'
                '<topicref href="b.dita"/></topicref></map>').encode(),
            'a.dita': b'<topic id="a"><body><p>see <xref keyref="k"/></p></body></topic>',
            'b.dita': b'<topic id="b"><body><p>see <xref keyref="k"/></p></body></topic>',
            'global.dita': b'<topic id="global"><body/></topic>',
            'local.dita': b'<topic id="local"><body/></topic>',
        }
        view = build_view(MemoryPackage(files), 'm.map', {})
        resolved = {entry['href']: entry['paragraphs'][0]['segments'][1]['resolved_href']
                    for entry in view['entries']}
        self.assertEqual(resolved['a.dita'], 'global.dita')
        self.assertEqual(resolved['b.dita'], 'local.dita')
        scoped = [row for row in view['keys'] if row['scope'] == 'scoped']
        self.assertEqual(scoped[0]['href'], 'local.dita')

    def test_path_normalization_rejects_escape_and_schemes(self):
        for bad in ('../x.dita', '/abs/path', 'https://host/x', 'a/../../x'):
            with self.assertRaises(ValueError):
                normalize_rel(bad)
        self.assertEqual(normalize_rel('a/../b/./c.dita'), 'b/c.dita')

    def test_directory_package_blocks_root_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            package = DirectoryPackage(directory)
            self.assertFalse(package.contains('../outside.dita'))
            with self.assertRaises(ValueError):
                package.read('../../etc/passwd')


class DirectoryPackageAndCliTests(unittest.TestCase):
    def test_directory_package_round_trip_and_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for rel, raw in product_package().items():
                target = root / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(raw)
            package = DirectoryPackage(root)
            view = build_view(package, 'maps/alpha-product.map',
                              {'product': 'alpha'})
            self.assertEqual([e['href'] for e in view['entries']][-1],
                             'topics/service-a.dita')
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                code = app.main(['view', str(root), 'maps/alpha-product.map',
                                 '--set', 'product=alpha'])
            self.assertEqual(code, 0)
            payload = json.loads(buffer.getvalue())
            self.assertEqual(payload['root_map'], 'maps/alpha-product.map')
            self.assertEqual(len(payload['entries']), 2)

    def test_viewdemo_shows_identity_and_impact(self):
        report = app.view_demo()
        self.assertNotEqual(report['same_file_distinct_entries']['alpha'],
                            report['same_file_distinct_entries']['beta'])
        for view in report['views']:
            self.assertEqual(view['diagnostic_count'], 0)
        affected = report['shared_resource_impact']['affected_root_maps']
        self.assertEqual(sorted(affected),
                         ['maps/alpha-product.map', 'maps/beta-product.map'])
        self.assertEqual(report['alpha_only_impact']['unaffected_root_maps'],
                         ['maps/beta-product.map'])
        self.assertGreaterEqual(len(report['shared_paragraph_occurrences']), 3)


if __name__ == '__main__':
    unittest.main()
