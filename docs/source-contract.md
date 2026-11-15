# 来源格式与业务语义

来源限定 DITA 常用 XML 子集，不加载外部 DTD。支持 map/topic、topicref/mapref、keyscope、keys/keyref、conref 的 topic/element 路径与 product/platform/audience 条件。嵌套 keyscope 按从近到远查找，分支 processing-role 继承。仅处理登记在本地包的资源；上下文身份为根 map、条件配置、展开路径。段落来源与出现位置分别保存，不要求完整 DITA-OT 排版。上述语义已在 `collector.py` 落地，诊断码与边界见 `docs/collection-view.md`。

本地演练夹具由 `sampledata.py` 生成，均为虚构业务数据。`sample` 是当前可查看输入，`invalid` 是边界失败输入，其余用于对照来源变体。生成不会下载资源。

本地 HTTP 演练器采用方法与原始路径作为路由键，值为按调用次数返回的响应数组，耗尽后维持最后一项。响应可定义 status、headers、text/base64、require_headers、chunk_bytes、disconnect_after。每次请求保留方法、路径、头与正文摘要表示，便于核对实际访问；演练器只监听回环地址。

原始输入上限 16 MiB 是现有查看入口的保护值，不代表未来持续采集需一次读完整来源。格式含义和截断错误不能被 HTTP 200 覆盖。
