def samples():
    rootmap = b'<map id="root"><topicref keyscope="new"><topicref keys="support" href="new.dita" processing-role="resource-only"/><topicref href="guide.dita" product="new"/></topicref><topicref keyscope="old"><topicref keys="support" href="old.dita" processing-role="resource-only"/><topicref href="guide.dita" product="old"/></topicref></map>'
    topic = b'<topic id="guide"><title>Guide</title><body><p id="shared">Read <xref keyref="support"/> before use.</p><p conref="common.dita#common/safety"/></body></topic>'
    return {'sample.xml': rootmap, 'guide.dita': topic,
            'common.dita': b'<topic id="common"><title>Shared</title><body><p id="safety">Wear gloves</p></body></topic>',
            'new.dita': b'<topic id="new"><title>New support</title><body/></topic>',
            'old.dita': b'<topic id="old"><title>Old support</title><body/></topic>',
            'invalid.xml': b'<map>'}
