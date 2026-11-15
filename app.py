import argparse
import base64
import json
from pathlib import Path
import sys
import tempfile

from collector import (Collection, DirectoryPackage, MemoryPackage,
                       build_view, normalize_rel)
from source import inspect_bytes
from sampledata import product_package, samples
from storage import Archive
from transport import ReplaySource, fetch

MAX_INPUT = 16*1024*1024

def read_input(path):
    with Path(path).open('rb') as handle:
        data = handle.read(MAX_INPUT+1)
    if len(data) > MAX_INPUT:
        raise ValueError('输入超过接收限制')
    return data

def parse_profile(values):
    profile = {}
    for value in values or []:
        if '=' not in value:
            raise ValueError('条件必须是 key=value 形式: ' + value)
        key, item = value.split('=', 1)
        profile[key.strip()] = item.strip()
    return profile

def load_package(source):
    root = Path(source)
    if root.is_dir():
        return DirectoryPackage(root)
    if root.is_file():
        return MemoryPackage(json.loads(root.read_text(encoding='utf-8')))
    raise ValueError('来源目录或包清单不存在: ' + source)

def view_demo():
    package = MemoryPackage(product_package())
    collection = Collection(package)
    alpha = collection.add_view('maps/alpha-product.map', {'product': 'alpha'})
    beta = collection.add_view('maps/beta-product.map', {'product': 'beta'})
    guide_ids = {}
    summaries = []
    for view in (alpha, beta):
        guide = next(entry for entry in view['entries']
                     if entry['href'].endswith('guide.dita'))
        guide_ids[view['profile']['product']] = guide['entry_id']
        support = next(segment for paragraph in guide['paragraphs']
                       for segment in paragraph['segments']
                       if segment.get('keyref') == 'support')
        summaries.append({
            'root_map': view['root_map'],
            'product': view['profile']['product'],
            'ordered_entries': [{'order': entry['order'], 'href': entry['href'],
                                 'title': entry['title'],
                                 'paragraphs': len(entry['paragraphs'])}
                                for entry in view['entries']],
            'resource_only': view['resources'],
            'support_key_resolves_to': support['resolved_href'],
            'filtered_out': [{'href': item['expansion_path'][-1]['href'],
                              'rejected_attribute': item['rejected_attribute']}
                             for item in view['filtered_out']],
            'diagnostic_count': len(view['diagnostics']),
        })
    impact = collection.impact('topics/common-notes.dita')
    alpha_only = collection.impact('topics/alpha-support.dita')
    provenance = collection.provenance('topics/common-notes.dita', 'safety')
    return {
        'same_file_distinct_entries': guide_ids,
        'views': summaries,
        'shared_resource_impact': {
            'resource': impact['resource'],
            'affected_root_maps': [item['root_map'] for item in impact['affected_views']],
        },
        'alpha_only_impact': {
            'resource': alpha_only['resource'],
            'affected_root_maps': [item['root_map'] for item in alpha_only['affected_views']],
            'unaffected_root_maps': [item['root_map'] for item in alpha_only['unaffected_views']],
        },
        'shared_paragraph_occurrences': [
            {'root_map': item['root_map'], 'entry_href': item['entry_href'],
             'paragraph_order': item['paragraph_order']}
            for item in provenance['occurrences']],
    }

def demo():
    fixtures = samples()
    name = next(key for key in fixtures if key.startswith('sample.'))
    data = fixtures[name]
    routes = {'GET /sample':[{'base64':base64.b64encode(data).decode()}]}
    with tempfile.TemporaryDirectory() as directory, ReplaySource(routes) as server:
        status, headers, raw = fetch(server.url + '/sample')
        if status != 200:
            raise ValueError('来源请求失败')
        rows = inspect_bytes(raw)
        with Archive(Path(directory)/'archive.sqlite3') as archive:
            first = archive.save('local-demo', raw, rows)
            repeated = archive.save('local-demo', raw, rows)
            return dict(input=name, bytes=len(raw), captures=len(archive.list()),
                        same_capture=first==repeated, rows=rows, requests=len(server.requests))

def main(argv=None):
    parser = argparse.ArgumentParser(description='来源检查与原件留存')
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('inspect', 'capture'):
        command = commands.add_parser(name)
        command.add_argument('path')
        if name == 'capture':
            command.add_argument('--database', required=True)
            command.add_argument('--source', required=True)
    listing = commands.add_parser('list')
    listing.add_argument('--database', required=True)
    fixtures = commands.add_parser('fixtures')
    fixtures.add_argument('directory')
    commands.add_parser('demo')
    view = commands.add_parser('view', help='按根 map 与条件构建采集视图')
    view.add_argument('source', help='本地 DITA 包目录或 JSON 包清单')
    view.add_argument('root_map')
    view.add_argument('--set', dest='conditions', action='append', default=[],
                      help='条件键值，如 product=alpha，可重复')
    impact = commands.add_parser('impact', help='查询资源改动影响哪些视图条目')
    impact.add_argument('source')
    impact.add_argument('resource')
    impact.add_argument('--view', dest='views', action='append', default=[],
                        help='root_map:product=value 形式，可重复；缺省时用包内全部 map')
    provenance = commands.add_parser('provenance', help='查询共享段落的来源链与出现位置')
    provenance.add_argument('source')
    provenance.add_argument('resource')
    provenance.add_argument('--element')
    provenance.add_argument('--view', dest='views', action='append', default=[])
    commands.add_parser('viewdemo', help='两套本地产品 map 的同键异义/过滤/共享段落演示')
    args = parser.parse_args(argv)
    try:
        if args.command == 'demo':
            result = demo()
        elif args.command == 'viewdemo':
            result = view_demo()
        elif args.command == 'view':
            result = build_view(load_package(args.source), normalize_rel(args.root_map),
                                parse_profile(args.conditions))
        elif args.command in ('impact', 'provenance'):
            package = load_package(args.source)
            collection = Collection(package)
            if args.views:
                for spec in args.views:
                    root, _, rest = spec.partition(':')
                    collection.add_view(root, parse_profile([rest] if rest else []))
            else:
                for map_path in package.map_files():
                    collection.add_view(map_path, {})
            if args.command == 'impact':
                result = collection.impact(args.resource)
            else:
                result = collection.provenance(args.resource, args.element)
        elif args.command == 'fixtures':
            destination = Path(args.directory)
            destination.mkdir(parents=True, exist_ok=True)
            for name, raw in samples().items():
                path = destination/name
                if path.exists():
                    raise ValueError('不覆盖已有夹具文件：'+name)
                path.write_bytes(raw)
            result = dict(files=sorted(samples()))
        elif args.command == 'list':
            with Archive(args.database) as archive:
                result = archive.list()
        else:
            raw = read_input(args.path)
            rows = inspect_bytes(raw)
            if args.command == 'inspect':
                result = rows
            else:
                with Archive(args.database) as archive:
                    result = dict(capture_id=archive.save(args.source,raw,rows), rows=len(rows))
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as error:
        print(json.dumps(dict(error=type(error).__name__, reason=str(error)), ensure_ascii=False), file=sys.stderr)
        return 2

if __name__ == '__main__':
    raise SystemExit(main())
