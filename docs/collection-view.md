# 上下文感知采集视图

`collector.py` 在 `source.py` 的单文件结构检查之上，按 **根 map + 条件配置**
构建采集视图。只处理登记在本地包内的资源（内存包或目录包），不加载外部
DTD，不访问公网。

## 条目身份：为什么文件路径不是唯一身份

最终条目的身份是 `(根 map, 条件 profile, 实际展开路径)` 的哈希，而不是
topic 文件路径。原因有三：

1. **同键异义**：不同根 map（或不同 keyscope）可以定义同名键，`keyref`
   按当前键空间解释。同一个 `guide.dita` 里的 `keyref="support"`，在
   alpha 视图解析到 `alpha-support.dita`，在 beta 视图解析到
   `beta-support.dita`——文件相同，链接含义不同，是两个条目。
2. **条件展开**：过滤作用在 map 树的实际 ref 上，被剪分支不会出现在
   展开路径里；同一 topic 可能只在某些产品条件下可达，条目携带的条件
   链不同。
3. **resource-only 与阅读目录分离**：`processing-role="resource-only"`
   的分支只登记为可引用资源与键定义，不生成阅读条目；同一路径可以既是
   某视图的资源，又是另一视图的正文来源。

## 处理规则

- 条件属性 `product/platform/audience` 在每个 ref 上按当前 profile 判定，
  不匹配的整支剪掉，并在 `filtered_out` 保留实际展开路径与拒绝原因。
- `keyscope` 形成嵌套键空间，键查找从最近作用域向全局回退；同名键就近
  遮蔽。作用域弹出后其键表仍保留在视图的 `keys` 清单里供审计。
- `mapref`/嵌套 map 随引用展开并做循环检测；循环被记录为
  `reference-cycle` 诊断并截断该支，不重复展开。
- 行内 `xref` 输出为结构化 `link` 片段（含 `keyref`、解析状态与解析后
  路径）；引用标签永远不会被当成正文文本。缺键产出 `unresolved-key`。
- `conref` 只接受包内、`文件#topic/element` 限定形式，支持
  `conrefend` 同主题范围；段落保留完整 `source_chain`（引用点 -> 最终
  来源元素）。越界、畸形、conref 循环分别产出
  `unsupported-boundary`、`malformed-conref`、`reference-cycle`。
- 所有诊断都带 `file`、`element` 与当时的 `expansion_path`，不静默丢引用。

## 影响面与段落溯源

- `Collection.impact(resource)` 基于每个视图的实际使用记录（map 引用、
  topic 引用、键目标、resource-only、conref 来源）判断该资源改动会影响
  哪些视图的哪些条目；未使用该资源的视图列入 `unaffected_views`，可据此
  只重采受影响的机型，而不是整包重采。
- `Collection.provenance(file, element)` 返回共享段落的来源链与其在每个
  视图里的最终出现位置（条目、段落序号）。

## CLI

```sh
python3 app.py view <包目录或 JSON 清单> <根 map 相对路径> --set product=alpha
python3 app.py impact <包目录> <资源相对路径> \
    --view maps/alpha-product.map:product=alpha \
    --view maps/beta-product.map:product=beta
python3 app.py provenance <包目录> topics/common-notes.dita --element safety \
    --view maps/alpha-product.map:product=alpha
python3 app.py viewdemo
```

`viewdemo` 使用 `sampledata.product_package()` 构造的两套虚构产品 map
（alpha 新型机 / beta 旧机型），演示同键 `support` 的不同解释、按产品
条件过滤维护步骤、resource-only 共享库，以及共享段落 `safety` 的来源链
与影响面，全程在内存中完成。
