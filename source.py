import xml.etree.ElementTree as ET

def inspect_bytes(data):
    root = ET.fromstring(data)
    result = []
    if root.tag not in ('map', 'topic'):
        raise ValueError('只查看 DITA map 或 topic')
    for index, node in enumerate(root.iter()):
        if node.tag in ('topicref', 'mapref', 'xref', 'p'):
            result.append({'index': index, 'tag': node.tag, 'href': node.get('href'),
                           'keys': node.get('keys'), 'keyref': node.get('keyref'),
                           'conref': node.get('conref')})
    return result
