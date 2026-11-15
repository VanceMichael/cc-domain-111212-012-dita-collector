"""按根 map 与产品条件构建 DITA 采集视图。

核心身份不是文件路径，而是 ``(根 map, 条件配置, 实际展开路径)``：
同一个 topic 在不同 keyscope / 产品条件下是不同条目，keyref 也按当前
键空间分别解释。resource-only 分支只登记资源与键，不进入阅读目录。
仅使用标准库，不加载外部 DTD。
"""
from __future__ import annotations

import hashlib
import json
import posixpath
import re
from pathlib import Path

import xml.etree.ElementTree as ET

FILTER_ATTRS = ('product', 'platform', 'audience')
BLOCK_TAGS = ('shortdesc', 'p', 'li', 'cmd', 'note')
REF_TAGS = ('topicref', 'mapref')
MAP_SUFFIXES = ('.map', '.ditamap')
SCHEME_RE = re.compile(r'^[a-zA-Z][a-zA-Z0-9+.-]*:')


def _digest(payload):
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()[:12]


def normalize_rel(path):
    """归一化包内相对路径；绝对地址、带协议地址或越界路径抛 ValueError。"""
    if path is None or path == '':
        raise ValueError('空路径')
    if path.startswith('/') or SCHEME_RE.match(path):
        raise ValueError('跨越包边界的地址: ' + path)
    normalized = posixpath.normpath(path.replace('\\', '/'))
    if normalized == '..' or normalized.startswith('../') or normalized.startswith('..\\'):
        raise ValueError('路径越出包根: ' + path)
    return normalized


def split_target(href):
    """分离路径与片段，返回 (path, fragment)。"""
    if '#' in href:
        return tuple(href.split('#', 1))
    return href, ''


class Package:
    """本地 DITA 包抽象，内存包与目录包共用同一接口。"""

    def contains(self, rel):
        raise NotImplementedError

    def read(self, rel):
        raise NotImplementedError

    def map_files(self):
        return sorted(p for p in self.files() if p.endswith(MAP_SUFFIXES))


class MemoryPackage(Package):
    def __init__(self, files):
        self._files = {normalize_rel(name): data for name, data in files.items()}

    def files(self):
        return sorted(self._files)

    def contains(self, rel):
        return normalize_rel(rel) in self._files

    def read(self, rel):
        return self._files[normalize_rel(rel)]


class DirectoryPackage(Package):
    def __init__(self, root):
        self.root = Path(root).resolve()
        if not self.root.is_dir():
            raise ValueError('来源目录不存在: ' + str(self.root))

    def _resolve(self, rel):
        target = (self.root / normalize_rel(rel)).resolve()
        if not target.is_relative_to(self.root):
            raise ValueError('路径越出包根: ' + rel)
        return target

    def files(self):
        return sorted(posixpath.join(*path.relative_to(self.root).parts)
                      for path in self.root.rglob('*') if path.is_file())

    def contains(self, rel):
        try:
            return self._resolve(rel).is_file()
        except ValueError:
            return False

    def read(self, rel):
        return self._resolve(rel).read_bytes()


def _diagnostic(code, file, detail, element=None, expansion_path=None):
    return {'code': code, 'severity': 'error', 'file': file,
            'element': element, 'expansion_path': list(expansion_path or []),
            'detail': detail}


class ViewBuilder:
    def __init__(self, package, root_map, profile):
        self.package = package
        self.root_map = normalize_rel(root_map)
        self.profile = dict(profile)
        self.diagnostics = []
        self.filtered_out = []
        self.entries = []
        self.resources = set()
        self.usage = {}
        self.global_keys = {}
        self.scope_stack = []
        self.scope_snapshots = []

    # -- 通用工具 ----------------------------------------------------------

    def _use(self, rel, reason):
        self.usage.setdefault(rel, set()).add(reason)

    def _resolve_href(self, href, base_file, expansion_path):
        target, _fragment = split_target(href)
        if SCHEME_RE.match(target) or target.startswith('/'):
            self.diagnostics.append(_diagnostic(
                'unsupported-boundary', base_file, '不支持的包外引用: ' + href,
                expansion_path=expansion_path))
            return None
        try:
            rel = normalize_rel(posixpath.join(posixpath.dirname(base_file), target))
        except ValueError as error:
            self.diagnostics.append(_diagnostic(
                'unsupported-boundary', base_file, str(error),
                expansion_path=expansion_path))
            return None
        if not self.package.contains(rel):
            self.diagnostics.append(_diagnostic(
                'missing-resource', base_file, '引用的资源不在包内: ' + rel,
                expansion_path=expansion_path))
            return None
        return rel

    def _read(self, rel, reason):
        self._use(rel, reason)
        try:
            return self.package.read(rel)
        except KeyError:
            self.diagnostics.append(_diagnostic('missing-resource', rel, '资源无法读取'))
        except OSError as error:
            self.diagnostics.append(_diagnostic('missing-resource', rel, str(error)))
        return None

    def _matches_profile(self, element):
        """条件作用于当前 ref；祖先链不匹配时整支已在更早一层被剪掉。"""
        for attr in FILTER_ATTRS:
            value = element.get(attr)
            if value is None:
                continue
            wanted = self.profile.get(attr)
            if wanted is None or wanted not in value.split():
                return False, attr, value
        return True, None, None

    # -- 键空间 ------------------------------------------------------------

    def _current_scope(self, create=False):
        if self.scope_stack:
            return self.scope_stack[-1]['keys']
        return self.global_keys

    def _register_keys(self, element, base_file, expansion_path):
        names = element.get('keys')
        if not names:
            return
        target = None
        href = element.get('href')
        if href:
            target = self._resolve_href(href, base_file, expansion_path)
            if target:
                self._use(target, 'key-target')
        table = self._current_scope()
        for name in names.split():
            table[name] = {'href': target, 'defined_in': base_file,
                           'scope': self.scope_stack[-1]['name'] if self.scope_stack else None}
    def _lookup_key(self, name):
        for scope in reversed(self.scope_stack):
            if name in scope['keys']:
                return scope['keys'][name]
        return self.global_keys.get(name)

    # -- map 展开 ----------------------------------------------------------

    def build(self):
        self._walk_map(self.root_map, [], [], False)
        view_id = _digest([self.root_map, sorted(self.profile.items())])
        return {
            'view_id': view_id,
            'root_map': self.root_map,
            'profile': self.profile,
            'entries': self.entries,
            'resources': sorted(self.resources),
            'keys': self._dump_keys(),
            'filtered_out': self.filtered_out,
            'diagnostics': self.diagnostics,
            'usage': {name: sorted(reasons) for name, reasons in sorted(self.usage.items())},
        }

    def _dump_keys(self):
        rows = []
        for name, definition in sorted(self.global_keys.items()):
            rows.append({'scope': None, 'key': name, **definition})
        for index, scope in enumerate(self.scope_snapshots):
            for name, definition in sorted(scope['keys'].items()):
                rows.append({'scope': scope['name'], 'key': name, **definition})
        return rows

    def _walk_map(self, map_path, expansion_path, map_stack, resource_only):
        if map_path in map_stack:
            self.diagnostics.append(_diagnostic(
                'reference-cycle', map_path,
                '地图引用循环: ' + ' -> '.join(map_stack + [map_path]),
                expansion_path=expansion_path))
            return
        raw = self._read(map_path, 'map-reference')
        if raw is None:
            return
        try:
            root = ET.fromstring(raw)
        except ET.ParseError as error:
            self.diagnostics.append(_diagnostic('invalid-document', map_path, str(error)))
            return
        if root.tag != 'map':
            self.diagnostics.append(_diagnostic(
                'invalid-document', map_path, 'map 引用目标不是 <map>: ' + root.tag))
            return
        for child in root:
            if child.tag in REF_TAGS:
                self._walk_ref(child, map_path, list(expansion_path),
                               map_stack + [map_path], resource_only)

    def _walk_ref(self, element, base_file, expansion_path, map_stack,
                  resource_only):
        ok, attr, value = self._matches_profile(element)
        path_here = expansion_path + [{
            'file': base_file, 'tag': element.tag,
            'href': element.get('href'), 'keyref': element.get('keyref'),
            'keyscope': element.get('keyscope'),
            'condition': {a: element.get(a) for a in FILTER_ATTRS if element.get(a)},
        }]
        if not ok:
            self.filtered_out.append({
                'expansion_path': path_here,
                'rejected_attribute': {attr: value},
                'profile': dict(self.profile),
            })
            return
        resource_only = resource_only or element.get('processing-role') == 'resource-only'
        pushed = False
        if element.get('keyscope'):
            scope = {'name': element.get('keyscope'), 'keys': {}}
            self.scope_stack.append(scope)
            self.scope_snapshots.append(scope)
            pushed = True
        try:
            self._register_keys(element, base_file, path_here)
            href = element.get('href')
            if not href and element.get('keyref'):
                definition = self._lookup_key(element.get('keyref'))
                if definition is None or not definition.get('href'):
                    self.diagnostics.append(_diagnostic(
                        'unresolved-key', base_file,
                        '缺少键定义: ' + element.get('keyref'),
                        element=element.tag, expansion_path=path_here))
                else:
                    href = definition['href']
            if href:
                rel = self._resolve_href(href, base_file, path_here)
                if rel:
                    if rel.endswith(MAP_SUFFIXES):
                        self._walk_map(rel, path_here,
                                       map_stack, resource_only)
                    elif resource_only:
                        self.resources.add(rel)
                        self._use(rel, 'resource-only')
                    else:
                        self._add_topic(rel, path_here)
            for child in element:
                if child.tag in REF_TAGS:
                    self._walk_ref(child, base_file, path_here, map_stack,
                                   resource_only)
        finally:
            if pushed:
                self.scope_stack.pop()

    # -- topic 与段落 ------------------------------------------------------

    def _add_topic(self, href, expansion_path):
        entry_id = _digest([self.root_map, sorted(self.profile.items()),
                            [step.get('href') or step.get('keyref') for step in expansion_path]
                            + [href],
                            [step.get('keyscope') for step in expansion_path]])
        raw = self._read(href, 'topic-reference')
        title = None
        paragraphs = []
        if raw is not None:
            try:
                topic_root = ET.fromstring(raw)
            except ET.ParseError as error:
                self.diagnostics.append(_diagnostic('invalid-document', href, str(error),
                                                    expansion_path=expansion_path))
                topic_root = None
            if topic_root is not None:
                if topic_root.tag != 'topic':
                    self.diagnostics.append(_diagnostic(
                        'invalid-document', href, 'topic 引用目标不是 <topic>: ' + topic_root.tag,
                        expansion_path=expansion_path))
                title_el = next((n for n in topic_root.iter() if n.tag == 'title'), None)
                title = ''.join(title_el.itertext()) if title_el is not None else None
                paragraphs = self._extract_blocks(href, topic_root, expansion_path, ())
        self.entries.append({
            'entry_id': entry_id,
            'order': len(self.entries),
            'href': href,
            'title': title,
            'resource_only': False,
            'conditions': [step['condition'] for step in expansion_path if step['condition']],
            'expansion_path': expansion_path,
            'paragraphs': paragraphs,
        })

    def _extract_blocks(self, file_path, topic_root, expansion_path, conref_stack):
        blocks = []

        def location(element, tag):
            return {'file': file_path, 'topic': topic_root.get('id'),
                    'element': element.get('id'), 'tag': tag}

        def walk(parent):
            for node in parent:
                if node.tag in BLOCK_TAGS:
                    blocks.extend(emit_block(node))
                else:
                    walk(node)

        def emit_block(element):
            if element.get('conref'):
                return self._resolve_conref(element, file_path, topic_root,
                                            expansion_path, conref_stack)
            return [{'tag': element.tag,
                     'segments': self._segments(element, file_path, expansion_path),
                     'source_chain': [location(element, element.tag)]}]

        walk(topic_root)
        for index, paragraph in enumerate(blocks):
            paragraph['order'] = index
        return blocks

    def _segments(self, element, file_path, expansion_path):
        """把行内内容拆成文本/链接片段；引用标签永远不变成正文文本。"""
        segments = []

        def add_text(text):
            if text:
                segments.append({'type': 'text', 'text': text})

        def rec(node):
            add_text(node.text)
            for child in node:
                if child.tag == 'xref':
                    segment = {'type': 'link', 'text': (''.join(child.itertext()) or None)}
                    if child.get('keyref'):
                        name = child.get('keyref')
                        segment['keyref'] = name
                        definition = self._lookup_key(name)
                        if definition is None or not definition.get('href'):
                            segment['status'] = 'unresolved'
                            self.diagnostics.append(_diagnostic(
                                'unresolved-key', file_path, '缺少键定义: ' + name,
                                element='xref', expansion_path=expansion_path))
                        else:
                            segment['status'] = 'resolved'
                            segment['resolved_href'] = definition['href']
                    elif child.get('href'):
                        rel = self._resolve_href(child.get('href'), file_path, expansion_path)
                        segment['href'] = child.get('href')
                        segment['status'] = 'resolved' if rel else 'unresolved'
                        if rel:
                            segment['resolved_href'] = rel
                    else:
                        segment['status'] = 'unresolved'
                    segments.append(segment)
                else:
                    rec(child)
                add_text(child.tail)

        rec(element)
        return segments

    def _parse_conref(self, value, base_file, expansion_path):
        path, fragment = split_target(value)
        if not fragment or '/' not in fragment:
            self.diagnostics.append(_diagnostic(
                'malformed-conref', base_file, 'conref 必须是 文件#topic/element 形式: ' + value,
                expansion_path=expansion_path))
            return None
        target_file = path or base_file
        try:
            rel = normalize_rel(posixpath.join(posixpath.dirname(base_file), target_file))
        except ValueError as error:
            self.diagnostics.append(_diagnostic(
                'unsupported-boundary', base_file, str(error),
                expansion_path=expansion_path))
            return None
        topic_id, element_id = fragment.split('/', 1)
        return rel, topic_id, element_id

    def _resolve_conref(self, element, file_path, topic_root, expansion_path, conref_stack):
        parsed = self._parse_conref(element.get('conref'), file_path, expansion_path)
        if parsed is None:
            return []
        rel, topic_id, element_id = parsed
        if not self.package.contains(rel):
            self.diagnostics.append(_diagnostic(
                'missing-resource', file_path,
                'conref 目标不在包内: ' + element.get('conref'),
                element=element.tag, expansion_path=expansion_path))
            return []
        raw = self._read(rel, 'conref-source')
        if raw is None:
            return []
        try:
            target_root = ET.fromstring(raw)
        except ET.ParseError as error:
            self.diagnostics.append(_diagnostic('invalid-document', rel, str(error)))
            return []
        if target_root.get('id') != topic_id:
            self.diagnostics.append(_diagnostic(
                'malformed-conref', rel, '片段主题标识不匹配: ' + topic_id,
                expansion_path=expansion_path))
            return []
        start = next((n for n in target_root.iter() if n.get('id') == element_id), None)
        if start is None:
            self.diagnostics.append(_diagnostic(
                'malformed-conref', rel, '找不到 conref 目标元素: ' + element_id,
                expansion_path=expansion_path))
            return []
        targets = [start]
        end_value = element.get('conrefend')
        if end_value:
            end_parsed = self._parse_conref(end_value, file_path, expansion_path)
            if end_parsed is None:
                return []
            end_rel, end_topic, end_id = end_parsed
            if (end_rel, end_topic) != (rel, topic_id):
                self.diagnostics.append(_diagnostic(
                    'malformed-conref', rel, 'conrefend 必须与起点位于同一主题',
                    expansion_path=expansion_path))
                return []
            parent_map = {child: parent for parent in target_root.iter() for child in parent}
            parent = parent_map.get(start)
            if parent is None:
                self.diagnostics.append(_diagnostic(
                    'malformed-conref', rel, '范围起点没有父节点', expansion_path=expansion_path))
                return []
            siblings = list(parent)
            start_index = siblings.index(start)
            end_index = next((i for i, node in enumerate(siblings[start_index:], start_index)
                              if node.get('id') == end_id), None)
            if end_index is None:
                self.diagnostics.append(_diagnostic(
                    'malformed-conref', rel, 'conrefend 终点不在起点之后: ' + end_id,
                    expansion_path=expansion_path))
                return []
            targets = siblings[start_index:end_index + 1]
        ref_location = {'file': file_path, 'topic': topic_root.get('id'),
                        'element': element.get('id'), 'tag': element.tag}
        paragraphs = []
        for target in targets:
            target_location = {'file': rel, 'topic': topic_id,
                               'element': target.get('id'), 'tag': target.tag}
            signature = (rel, target.get('id'))
            if signature in conref_stack:
                self.diagnostics.append(_diagnostic(
                    'reference-cycle', file_path,
                    'conref 循环: ' + ' -> '.join('/'.join(part) for part in
                                                  conref_stack + (signature,)),
                    expansion_path=expansion_path))
                continue
            if target.get('conref'):
                nested = self._resolve_conref(target, rel, target_root,
                                              expansion_path, conref_stack + (signature,))
                for paragraph in nested:
                    paragraph['source_chain'] = [ref_location] + paragraph['source_chain']
                    paragraphs.append(paragraph)
            else:
                paragraphs.append({
                    'tag': target.tag,
                    'segments': self._segments(target, rel, expansion_path),
                    'source_chain': [ref_location, target_location],
                })
        return paragraphs


def build_view(package, root_map, profile):
    return ViewBuilder(package, normalize_rel(root_map), profile).build()


class Collection:
    """多个根 map 视图的集合，提供影响面与复用段落溯源查询。"""

    def __init__(self, package):
        self.package = package
        self.views = []

    def add_view(self, root_map, profile):
        view = build_view(self.package, root_map, profile)
        self.views.append(view)
        return view

    def impact(self, resource):
        resource = normalize_rel(resource)
        affected, unaffected = [], []
        for view in self.views:
            reasons = view['usage'].get(resource)
            if not reasons:
                unaffected.append({'view_id': view['view_id'], 'root_map': view['root_map']})
                continue
            entries = []
            for entry in view['entries']:
                touched = entry['href'] == resource or any(
                    loc['file'] == resource
                    for paragraph in entry['paragraphs']
                    for loc in paragraph['source_chain'])
                if touched:
                    entries.append({'entry_id': entry['entry_id'], 'href': entry['href'],
                                    'order': entry['order']})
            affected.append({'view_id': view['view_id'], 'root_map': view['root_map'],
                             'product': view['profile'].get('product'),
                             'reasons': sorted(reasons), 'entries': entries})
        return {'resource': resource, 'affected_views': affected,
                'unaffected_views': unaffected}

    def provenance(self, file_path, element_id=None):
        file_path = normalize_rel(file_path)
        occurrences = []
        for view in self.views:
            for entry in view['entries']:
                for paragraph in entry['paragraphs']:
                    chain = paragraph['source_chain']
                    if not any(loc['file'] == file_path
                               and (element_id is None or loc.get('element') == element_id)
                               for loc in chain):
                        continue
                    occurrences.append({
                        'view_id': view['view_id'], 'root_map': view['root_map'],
                        'product': view['profile'].get('product'),
                        'entry_id': entry['entry_id'], 'entry_href': entry['href'],
                        'paragraph_order': paragraph['order'],
                        'source_chain': chain,
                    })
        return {'resource': file_path, 'element': element_id, 'occurrences': occurrences}
