def samples():
    rootmap = b'<map id="root"><topicref keyscope="new"><topicref keys="support" href="new.dita" processing-role="resource-only"/><topicref href="guide.dita" product="new"/></topicref><topicref keyscope="old"><topicref keys="support" href="old.dita" processing-role="resource-only"/><topicref href="guide.dita" product="old"/></topicref></map>'
    topic = b'<topic id="guide"><title>Guide</title><body><p id="shared">Read <xref keyref="support"/> before use.</p><p conref="common.dita#common/safety"/></body></topic>'
    return {'sample.xml': rootmap, 'guide.dita': topic,
            'common.dita': b'<topic id="common"><title>Shared</title><body><p id="safety">Wear gloves</p></body></topic>',
            'new.dita': b'<topic id="new"><title>New support</title><body/></topic>',
            'old.dita': b'<topic id="old"><title>Old support</title><body/></topic>',
            'invalid.xml': b'<map>'}


def product_package():
    """两套产品 map 共用同一批 topic/资源库的虚构本地 DITA 包。

    alpha（新型机）与 beta（旧机型）的根 map 各自定义同键 ``support``，
    并在不同 product 条件下引用共享 map/topic；``shared-lib`` 是
    resource-only 库，只提供键与 conref 段落，不进入阅读目录。
    """
    alpha_map = (
        '<map id="alpha-map">'
        '<title>Alpha 机型帮助</title>'
        '<topicref keys="support" href="../topics/alpha-support.dita" processing-role="resource-only"/>'
        '<topicref href="../topics/guide.dita"/>'
        '<topicref href="maintenance.map"/>'
        '<topicref href="shared-lib.map" processing-role="resource-only"/>'
        '</map>')
    beta_map = (
        '<map id="beta-map">'
        '<title>Beta 机型帮助</title>'
        '<topicref keys="support" href="../topics/beta-support.dita" processing-role="resource-only"/>'
        '<topicref href="../topics/guide.dita"/>'
        '<topicref href="maintenance.map"/>'
        '<topicref href="shared-lib.map" processing-role="resource-only"/>'
        '</map>')
    maintenance_map = (
        '<map id="maintenance-map">'
        '<topicref href="../topics/service-a.dita" product="alpha"/>'
        '<topicref href="../topics/service-b.dita" product="beta"/>'
        '<topicref href="../topics/troubleshooting.dita" audience="service"/>'
        '</map>')
    shared_lib_map = (
        '<map id="shared-lib">'
        '<topicref keys="policy" href="../topics/common-notes.dita" processing-role="resource-only"/>'
        '</map>')
    guide = (
        '<topic id="guide"><title>通用操作指南</title><body>'
        '<shortdesc>开始前请查看 <xref keyref="support">支持资源</xref>。</shortdesc>'
        '<p id="intro">本机型专用流程见 <xref keyref="support"/>，'
        '或直接查阅 <xref href="alpha-support.dita">机型页</xref>。</p>'
        '<p conref="common-notes.dita#common-notes/safety"/>'
        '</body></topic>')
    alpha_support = (
        '<topic id="alpha-support"><title>Alpha 支持门户</title><body>'
        '<p id="alpha-only">Alpha 专用固件升级步骤。</p></body></topic>')
    beta_support = (
        '<topic id="beta-support"><title>Beta 支持门户</title><body>'
        '<p id="beta-only">Beta 保留的手动校准步骤。</p></body></topic>')
    service_a = (
        '<topic id="service-a"><title>Alpha 维护（新流程）</title><body>'
        '<p id="a-step">执行自动诊断后复位。</p>'
        '<p conref="../topics/common-notes.dita#common-notes/safety"/></body></topic>')
    service_b = (
        '<topic id="service-b"><title>Beta 维护（旧流程）</title><body>'
        '<p id="b-step">拆开外壳手动校准。</p>'
        '<p conref="../topics/common-notes.dita#common-notes/range-start" '
        'conrefend="../topics/common-notes.dita#common-notes/range-end"/></body></topic>')
    troubleshooting = (
        '<topic id="troubleshooting"><title>故障排查</title><body>'
        '<p id="ts-1">先复位再重试。</p></body></topic>')
    common_notes = (
        '<topic id="common-notes"><title>共享注意事项库</title><body>'
        '<p id="safety">作业前佩戴防护手套并断电。</p>'
        '<p id="range-start">范围第一步：确认铭牌。</p>'
        '<p id="range-mid">范围第二步：记录序列号。</p>'
        '<p id="range-end">范围第三步：回贴封条。</p>'
        '</body></topic>')
    missing_key_topic = (
        '<topic id="broken"><title>缺键主题</title><body>'
        '<p id="bad">访问 <xref keyref="no-such-key">不存在的键</xref></p></body></topic>')
    cycle_map_a = '<map id="cycle-a"><topicref href="cycle-b.map"/></map>'
    cycle_map_b = '<map id="cycle-b"><topicref href="cycle-a.map"/></map>'
    cross_topic = (
        '<topic id="cross"><title>越界主题</title><body>'
        '<p conref="../../outside.dita#x/y"/></body></topic>')
    malformed_topic = (
        '<topic id="malformed"><title>格式错误主题</title><body>'
        '<p conref="common-notes.dita#safety"/></body></topic>')
    return {
        'maps/alpha-product.map': alpha_map.encode(),
        'maps/beta-product.map': beta_map.encode(),
        'maps/maintenance.map': maintenance_map.encode(),
        'maps/shared-lib.map': shared_lib_map.encode(),
        'maps/cycle-a.map': cycle_map_a.encode(),
        'maps/cycle-b.map': cycle_map_b.encode(),
        'topics/guide.dita': guide.encode(),
        'topics/alpha-support.dita': alpha_support.encode(),
        'topics/beta-support.dita': beta_support.encode(),
        'topics/service-a.dita': service_a.encode(),
        'topics/service-b.dita': service_b.encode(),
        'topics/troubleshooting.dita': troubleshooting.encode(),
        'topics/common-notes.dita': common_notes.encode(),
        'topics/missing-key.dita': missing_key_topic.encode(),
        'topics/cross-boundary.dita': cross_topic.encode(),
        'topics/malformed-conref.dita': malformed_topic.encode(),
    }
