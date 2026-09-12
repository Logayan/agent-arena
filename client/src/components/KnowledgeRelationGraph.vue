<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Eye, EyeOff, Maximize2, Minus, Plus, RefreshCw, Search, X } from '@lucide/vue'

type Json = Record<string, any>
type Position = { x: number; y: number; vx: number; vy: number }
type RelationView = Json & { outgoing: boolean; other?: Json }

const props = defineProps<{ graph: Json }>()
const emit = defineEmits<{ openSource: [node: Json] }>()

const host = ref<HTMLElement | null>(null)
const width = ref(980)
const height = ref(620)
const scale = ref(1)
const pan = ref({ x: 0, y: 0 })
const positions = ref<Record<string, Position>>({})
const query = ref('')
const showEdgeLabels = ref(true)
const enabledTypes = ref<string[]>([])
const enabledRelations = ref<string[]>([])
const selectedNodeId = ref('')
const selectedEdgeId = ref('')
let resizeObserver: ResizeObserver | null = null
let draggingNodeId = ''
let panning = false
let pointerStart = { x: 0, y: 0, panX: 0, panY: 0 }

const typeConfig: Record<string, { label: string; color: string; stroke: string; icon: string; radius: number }> = {
  realm: { label: '大江湖', color: '#efb64a', stroke: '#7a4c20', icon: '江', radius: 34 },
  team: { label: '小江湖', color: '#75c58b', stroke: '#245d45', icon: '队', radius: 29 },
  agent: { label: '人物', color: '#f09a6d', stroke: '#743f2e', icon: '人', radius: 25 },
  folder: { label: '目录', color: '#7fc0da', stroke: '#315f73', icon: '录', radius: 22 },
  source: { label: '知识来源', color: '#b599df', stroke: '#59427a', icon: '源', radius: 25 },
  concept: { label: '知识实体', color: '#ec6f8c', stroke: '#7f2e48', icon: '识', radius: 23 },
}

const relationLabels: Record<string, string> = {
  contains: '包含', member: '成员', knowledge: '知识归属', inherited_by: '继承', authorized: '授权',
  describes: '抽取实体', mentions: '提及',
}
const propertyLabels: Record<string, string> = {
  owner_name: '发起人', world_type: '江湖类型', purpose: '共同使命', operating_mode: '行事方式', member_count: '成员数',
  role: '职业身份', capabilities: '能力', runtime: '运行底座', memory_count: '长期记忆数', status: '索引状态',
  relative_path: '来源路径', path: '目录路径', scope_id: '归属对象', scope_type: '知识范围', media_type: '文件类型',
  chunk_count: '片段数', parser: '解析器', version: '版本', updated_at: '更新时间', source_count: '来源数', locator: '证据定位',
}
const constructionStageLabels: Record<string, string> = {
  source: '来源', chunk: '切片', ontology: '本体约束', entity_relation: '实体关系', evidence_binding: '证据绑定', visualization: '关系可视化',
}

const allNodes = computed<Json[]>(() => props.graph?.nodes ?? [])
const allEdges = computed<Json[]>(() => props.graph?.edges ?? [])
const nodeMap = computed<Record<string, Json>>(() => Object.fromEntries(allNodes.value.map(node => [String(node.id), node])))
const entityTypes = computed(() => {
  const counts = new Map<string, number>()
  allNodes.value.forEach(node => counts.set(String(node.type), (counts.get(String(node.type)) ?? 0) + 1))
  return [...counts.entries()].map(([type, count]) => ({ type, count, ...(typeConfig[type] ?? { label: type, color: '#91a4a1', stroke: '#435957', icon: '点', radius: 22 }) }))
})
const relationTypes = computed(() => {
  const counts = new Map<string, number>()
  allEdges.value.forEach(edge => counts.set(String(edge.type), (counts.get(String(edge.type)) ?? 0) + 1))
  return [...counts.entries()].map(([type, count]) => ({ type, count, label: relationLabels[type] ?? type }))
})

const queryVisibleIds = computed(() => {
  const keyword = query.value.trim().toLowerCase()
  if (!keyword) return null
  const matched = new Set(
    allNodes.value
      .filter(node => `${node.label} ${node.subtitle} ${JSON.stringify(node.properties ?? {})}`.toLowerCase().includes(keyword))
      .map(node => String(node.id)),
  )
  allEdges.value.forEach(edge => {
    if (matched.has(String(edge.source)) || matched.has(String(edge.target))) {
      matched.add(String(edge.source))
      matched.add(String(edge.target))
    }
  })
  return matched
})

const visibleNodes = computed(() => allNodes.value.filter(node =>
  enabledTypes.value.includes(String(node.type)) && (!queryVisibleIds.value || queryVisibleIds.value.has(String(node.id))),
))
const visibleNodeIds = computed(() => new Set(visibleNodes.value.map(node => String(node.id))))
const visibleEdges = computed(() => allEdges.value.filter(edge =>
  enabledRelations.value.includes(String(edge.type))
    && visibleNodeIds.value.has(String(edge.source))
    && visibleNodeIds.value.has(String(edge.target)),
))
const selectedNode = computed(() => nodeMap.value[selectedNodeId.value])
const selectedEdge = computed(() => allEdges.value.find(edge => String(edge.id) === selectedEdgeId.value))
const selectedItem = computed(() => selectedNode.value ?? selectedEdge.value)
const selectedConnectedIds = computed(() => {
  const result = new Set<string>()
  if (!selectedNodeId.value) return result
  result.add(selectedNodeId.value)
  allEdges.value.forEach(edge => {
    if (String(edge.source) === selectedNodeId.value) result.add(String(edge.target))
    if (String(edge.target) === selectedNodeId.value) result.add(String(edge.source))
  })
  return result
})
const selectedRelations = computed<RelationView[]>(() => {
  if (!selectedNode.value) return []
  return allEdges.value
    .filter(edge => String(edge.source) === selectedNodeId.value || String(edge.target) === selectedNodeId.value)
    .map(edge => {
      const outgoing = String(edge.source) === selectedNodeId.value
      const otherId = String(outgoing ? edge.target : edge.source)
      return { ...edge, outgoing, other: nodeMap.value[otherId] } as RelationView
    })
})
const graphTransform = computed(() => `translate(${pan.value.x} ${pan.value.y}) scale(${scale.value})`)

function nodeStyle(type: string) {
  return typeConfig[type] ?? { label: type, color: '#91a4a1', stroke: '#435957', icon: '点', radius: 22 }
}

function seededUnit(value: string): number {
  let hash = 2166136261
  for (let index = 0; index < value.length; index += 1) hash = Math.imul(hash ^ value.charCodeAt(index), 16777619)
  return ((hash >>> 0) % 10000) / 10000
}

function buildLayout(): void {
  const nodes = allNodes.value
  const edges = allEdges.value
  if (!nodes.length) {
    positions.value = {}
    return
  }
  const w = Math.max(720, width.value)
  const h = Math.max(520, height.value)
  const next: Record<string, Position> = {}
  const typeOrder = ['realm', 'team', 'agent', 'concept', 'source', 'folder']
  nodes.forEach((node, index) => {
    const ring = Math.max(0, typeOrder.indexOf(String(node.type)))
    const angle = seededUnit(String(node.id)) * Math.PI * 2 + index * 0.19
    const radius = ring === 0 ? 0 : 95 + ring * 42 + seededUnit(`${node.id}:radius`) * 90
    next[String(node.id)] = {
      x: w / 2 + Math.cos(angle) * radius,
      y: h / 2 + Math.sin(angle) * radius * 0.72,
      vx: 0,
      vy: 0,
    }
  })
  const nodeIds = nodes.map(node => String(node.id))
  const nodeIndex = Object.fromEntries(nodeIds.map((id, index) => [id, index]))
  for (let tick = 0; tick < 180; tick += 1) {
    const heat = 1 - tick / 210
    for (let leftIndex = 0; leftIndex < nodeIds.length; leftIndex += 1) {
      const left = next[nodeIds[leftIndex]]
      for (let rightIndex = leftIndex + 1; rightIndex < nodeIds.length; rightIndex += 1) {
        const right = next[nodeIds[rightIndex]]
        let dx = right.x - left.x
        let dy = right.y - left.y
        const distanceSquared = Math.max(90, dx * dx + dy * dy)
        const distance = Math.sqrt(distanceSquared)
        dx /= distance
        dy /= distance
        const force = Math.min(4.8, 3900 / distanceSquared) * heat
        left.vx -= dx * force
        left.vy -= dy * force
        right.vx += dx * force
        right.vy += dy * force
      }
    }
    edges.forEach(edge => {
      const source = next[String(edge.source)]
      const target = next[String(edge.target)]
      if (!source || !target) return
      const dx = target.x - source.x
      const dy = target.y - source.y
      const distance = Math.max(1, Math.sqrt(dx * dx + dy * dy))
      const targetDistance = String(edge.type) === 'contains' ? 145 : (String(edge.type) === 'mentions' ? 115 : 128)
      const force = (distance - targetDistance) * 0.011 * heat
      source.vx += (dx / distance) * force
      source.vy += (dy / distance) * force
      target.vx -= (dx / distance) * force
      target.vy -= (dy / distance) * force
    })
    nodeIds.forEach(id => {
      const point = next[id]
      point.vx += (w / 2 - point.x) * 0.0009
      point.vy += (h / 2 - point.y) * 0.0009
      const fixedCenter = nodeIndex[id] === 0 && nodes[0]?.type === 'realm'
      if (fixedCenter) {
        point.x += (w / 2 - point.x) * 0.28
        point.y += (h / 2 - point.y) * 0.28
      } else {
        point.x = Math.max(50, Math.min(w - 50, point.x + point.vx))
        point.y = Math.max(60, Math.min(h - 60, point.y + point.vy))
      }
      point.vx *= 0.76
      point.vy *= 0.76
    })
  }
  positions.value = next
  fitGraph()
}

function position(nodeId: string): Position {
  return positions.value[nodeId] ?? { x: width.value / 2, y: height.value / 2, vx: 0, vy: 0 }
}

function edgePath(edge: Json): string {
  const source = position(String(edge.source))
  const target = position(String(edge.target))
  const dx = target.x - source.x
  const dy = target.y - source.y
  const length = Math.max(1, Math.sqrt(dx * dx + dy * dy))
  const curve = Math.min(34, Math.max(10, length * 0.08)) * (seededUnit(String(edge.id)) > 0.5 ? 1 : -1)
  const middleX = (source.x + target.x) / 2 - (dy / length) * curve
  const middleY = (source.y + target.y) / 2 + (dx / length) * curve
  return `M ${source.x} ${source.y} Q ${middleX} ${middleY} ${target.x} ${target.y}`
}

function edgeLabelPosition(edge: Json) {
  const source = position(String(edge.source))
  const target = position(String(edge.target))
  return { x: (source.x + target.x) / 2, y: (source.y + target.y) / 2 - 5 }
}

function nodeOpacity(node: Json): number {
  if (!selectedItem.value) return 1
  if (selectedNodeId.value) return selectedConnectedIds.value.has(String(node.id)) ? 1 : 0.16
  const edge = selectedEdge.value
  return edge && [String(edge.source), String(edge.target)].includes(String(node.id)) ? 1 : 0.2
}

function edgeOpacity(edge: Json): number {
  if (!selectedItem.value) return 0.72
  if (selectedEdgeId.value) return String(edge.id) === selectedEdgeId.value ? 1 : 0.08
  return [String(edge.source), String(edge.target)].includes(selectedNodeId.value) ? 1 : 0.08
}

function shortLabel(value: unknown, length = 12): string {
  const text = String(value ?? '')
  return text.length > length ? `${text.slice(0, length)}…` : text
}

function toggleType(type: string): void {
  enabledTypes.value = enabledTypes.value.includes(type)
    ? enabledTypes.value.filter(item => item !== type)
    : [...enabledTypes.value, type]
}

function toggleRelation(type: string): void {
  enabledRelations.value = enabledRelations.value.includes(type)
    ? enabledRelations.value.filter(item => item !== type)
    : [...enabledRelations.value, type]
}

function selectNode(node: Json): void {
  selectedNodeId.value = String(node.id)
  selectedEdgeId.value = ''
}

function selectEdge(edge: Json): void {
  selectedEdgeId.value = String(edge.id)
  selectedNodeId.value = ''
}

function clearSelection(): void {
  selectedNodeId.value = ''
  selectedEdgeId.value = ''
}

function zoomBy(factor: number): void {
  scale.value = Math.max(0.35, Math.min(2.6, scale.value * factor))
}

function fitGraph(): void {
  scale.value = allNodes.value.length > 45 ? 0.72 : (allNodes.value.length > 20 ? 0.84 : 0.96)
  pan.value = { x: 0, y: 0 }
}

function handleWheel(event: WheelEvent): void {
  if (!host.value) return
  const rect = host.value.getBoundingClientRect()
  const previousScale = scale.value
  const nextScale = Math.max(0.35, Math.min(2.6, previousScale * (event.deltaY < 0 ? 1.12 : 0.89)))
  const cursorX = event.clientX - rect.left
  const cursorY = event.clientY - rect.top
  const graphX = (cursorX - pan.value.x) / previousScale
  const graphY = (cursorY - pan.value.y) / previousScale
  scale.value = nextScale
  pan.value = { x: cursorX - graphX * nextScale, y: cursorY - graphY * nextScale }
}

function beginPan(event: PointerEvent): void {
  if (event.button !== 0) return
  panning = true
  pointerStart = { x: event.clientX, y: event.clientY, panX: pan.value.x, panY: pan.value.y }
}

function beginNodeDrag(event: PointerEvent, node: Json): void {
  draggingNodeId = String(node.id)
  selectNode(node)
  event.preventDefault()
}

function handlePointerMove(event: PointerEvent): void {
  if (draggingNodeId && host.value) {
    const rect = host.value.getBoundingClientRect()
    const point = positions.value[draggingNodeId]
    if (point) {
      point.x = (event.clientX - rect.left - pan.value.x) / scale.value
      point.y = (event.clientY - rect.top - pan.value.y) / scale.value
      positions.value = { ...positions.value }
    }
    return
  }
  if (panning) {
    pan.value = {
      x: pointerStart.panX + event.clientX - pointerStart.x,
      y: pointerStart.panY + event.clientY - pointerStart.y,
    }
  }
}

function endPointer(): void {
  draggingNodeId = ''
  panning = false
}

function openSelectedSource(): void {
  if (selectedNode.value?.type === 'source') emit('openSource', selectedNode.value)
}

function relationDirection(relation: Json): string {
  return relation.outgoing ? `${relation.label} →` : `← ${relation.label}`
}

function propertyLabel(key: string | number): string {
  return propertyLabels[String(key)] ?? String(key)
}

function resetFilters(): void {
  query.value = ''
  enabledTypes.value = entityTypes.value.map(item => item.type)
  enabledRelations.value = relationTypes.value.map(item => item.type)
  clearSelection()
  buildLayout()
}

watch(
  () => props.graph,
  async () => {
    enabledTypes.value = entityTypes.value.map(item => item.type)
    enabledRelations.value = relationTypes.value.map(item => item.type)
    clearSelection()
    await nextTick()
    buildLayout()
  },
  { deep: true, immediate: true },
)

onMounted(() => {
  resizeObserver = new ResizeObserver(entries => {
    const rect = entries[0]?.contentRect
    if (!rect) return
    width.value = Math.max(680, rect.width)
    height.value = Math.max(520, rect.height)
    buildLayout()
  })
  if (host.value) resizeObserver.observe(host.value)
  window.addEventListener('pointermove', handlePointerMove)
  window.addEventListener('pointerup', endPointer)
})

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  window.removeEventListener('pointermove', handlePointerMove)
  window.removeEventListener('pointerup', endPointer)
})
</script>

<template>
  <section class="relationship-graph">
    <header class="graph-toolbar">
      <div>
        <strong>知识关系网络</strong>
        <small>参考 Graph Relationship Visualization：从来源片段抽取实体，展示组织、人物、知识、授权、继承、提及与证据关系</small>
      </div>
      <label><Search /><input v-model="query" placeholder="搜索人物、团队、文件或知识实体" /></label>
      <div class="graph-tool-actions">
        <button title="缩小" @click="zoomBy(0.86)"><Minus /></button>
        <b>{{ Math.round(scale * 100) }}%</b>
        <button title="放大" @click="zoomBy(1.16)"><Plus /></button>
        <button title="适应画布" @click="fitGraph"><Maximize2 /></button>
        <button title="重新布局" @click="buildLayout"><RefreshCw /></button>
        <button :title="showEdgeLabels ? '隐藏关系名称' : '显示关系名称'" @click="showEdgeLabels = !showEdgeLabels"><Eye v-if="showEdgeLabels" /><EyeOff v-else /></button>
      </div>
    </header>

    <div class="graph-filters">
      <div class="entity-filters"><span>实体</span><button v-for="item in entityTypes" :key="item.type" :class="{ active: enabledTypes.includes(item.type) }" @click="toggleType(item.type)"><i :style="{ background: item.color }"></i>{{ item.label }}<b>{{ item.count }}</b></button></div>
      <div class="relation-filters"><span>关系</span><button v-for="item in relationTypes" :key="item.type" :class="{ active: enabledRelations.includes(item.type) }" @click="toggleRelation(item.type)">{{ item.label }}<b>{{ item.count }}</b></button></div>
      <button class="reset-filter" @click="resetFilters">重置</button>
    </div>

    <div ref="host" class="graph-stage" @wheel.prevent="handleWheel" @pointerdown="beginPan" @click="clearSelection">
      <svg :width="width" :height="height" role="img" aria-label="知识与社会关系图">
        <defs>
          <marker id="relation-arrow" markerWidth="8" markerHeight="8" refX="19" refY="4" orient="auto" markerUnits="strokeWidth"><path d="M0,0 L8,4 L0,8 z" /></marker>
          <filter id="node-shadow" x="-30%" y="-30%" width="160%" height="160%"><feDropShadow dx="0" dy="3" stdDeviation="3" flood-opacity=".24" /></filter>
        </defs>
        <g :transform="graphTransform">
          <g class="graph-edges">
            <g v-for="edge in visibleEdges" :key="edge.id" :class="['graph-edge', { selected: selectedEdgeId === String(edge.id) }]" :style="{ opacity: edgeOpacity(edge) }" @pointerdown.stop @click.stop="selectEdge(edge)">
              <path class="edge-hit" :d="edgePath(edge)" />
              <path class="edge-line" :data-type="edge.type" :d="edgePath(edge)" marker-end="url(#relation-arrow)" />
            </g>
          </g>
          <g class="graph-nodes">
            <g v-for="node in visibleNodes" :key="node.id" :class="['graph-node', { selected: selectedNodeId === String(node.id) }]" :transform="`translate(${position(String(node.id)).x} ${position(String(node.id)).y})`" :style="{ opacity: nodeOpacity(node) }" @pointerdown.stop="beginNodeDrag($event, node)" @click.stop="selectNode(node)">
              <circle class="node-halo" :r="nodeStyle(node.type).radius + 7" />
              <circle class="node-body" :r="nodeStyle(node.type).radius" :fill="nodeStyle(node.type).color" :stroke="nodeStyle(node.type).stroke" />
              <text class="node-icon" text-anchor="middle" dominant-baseline="central">{{ nodeStyle(node.type).icon }}</text>
              <text class="node-label" text-anchor="middle" :y="nodeStyle(node.type).radius + 17">{{ shortLabel(node.label) }}</text>
              <text class="node-subtitle" text-anchor="middle" :y="nodeStyle(node.type).radius + 29">{{ shortLabel(node.subtitle, 16) }}</text>
            </g>
          </g>
          <g v-if="showEdgeLabels" class="graph-edge-labels">
            <text v-for="edge in visibleEdges" :key="`label:${edge.id}`" :class="['edge-label', { selected: selectedEdgeId === String(edge.id) }]" :x="edgeLabelPosition(edge).x" :y="edgeLabelPosition(edge).y" :style="{ opacity: edgeOpacity(edge) }" @pointerdown.stop @click.stop="selectEdge(edge)">{{ edge.label }}<tspan v-if="Number(edge.weight) > 1"> · {{ edge.weight }}</tspan></text>
          </g>
        </g>
      </svg>

      <div v-if="!visibleNodes.length" class="graph-empty"><span>⌁</span><strong>当前筛选条件下没有实体</strong><small>恢复实体类型或清空搜索词后重新查看。</small></div>
      <div class="graph-operation-hint">滚轮缩放 · 拖动画布 · 拖动节点 · 点击节点或关系查看证据</div>

      <aside v-if="selectedItem" class="graph-detail" @pointerdown.stop @click.stop>
        <header>
          <div><small>{{ selectedNode ? '实体详情' : '关系详情' }}</small><strong>{{ selectedNode?.label ?? selectedEdge?.label }}</strong></div>
          <button @click="clearSelection"><X /></button>
        </header>
        <template v-if="selectedNode">
          <div class="detail-type"><i :style="{ background: nodeStyle(selectedNode.type).color }"></i>{{ nodeStyle(selectedNode.type).label }}<b>{{ selectedNode.subtitle }}</b></div>
          <p v-if="selectedNode.properties?.description">{{ selectedNode.properties.description }}</p>
          <dl><template v-for="(value, key) in selectedNode.properties" :key="key"><div v-if="!['description','excerpt'].includes(String(key)) && value !== '' && value !== undefined"><dt>{{ propertyLabel(key) }}</dt><dd>{{ Array.isArray(value) ? value.join('、') : value }}</dd></div></template></dl>
          <blockquote v-if="selectedNode.properties?.excerpt">{{ selectedNode.properties.excerpt }}</blockquote>
          <section><header><strong>直接关系</strong><b>{{ selectedRelations.length }}</b></header><button v-for="relation in selectedRelations.slice(0, 14)" :key="relation.id" @click="relation.other && selectNode(relation.other)"><span>{{ relationDirection(relation) }}</span><b>{{ relation.other?.label ?? '未知实体' }}</b><small v-if="relation.evidence?.length">{{ relation.evidence.length }} 条证据</small></button></section>
          <button v-if="selectedNode.type === 'source'" class="open-source" @click="openSelectedSource">查看来源原文与 RAG 片段</button>
        </template>
        <template v-else-if="selectedEdge">
          <div class="relation-route"><button @click="nodeMap[selectedEdge.source] && selectNode(nodeMap[selectedEdge.source])">{{ nodeMap[selectedEdge.source]?.label }}</button><span>{{ selectedEdge.label }}</span><button @click="nodeMap[selectedEdge.target] && selectNode(nodeMap[selectedEdge.target])">{{ nodeMap[selectedEdge.target]?.label }}</button></div>
          <p>关系类型：{{ relationLabels[selectedEdge.type] ?? selectedEdge.type }} · 权重 {{ selectedEdge.weight ?? 1 }}</p>
          <section v-if="selectedEdge.evidence?.length"><header><strong>来源证据</strong><b>{{ selectedEdge.evidence.length }}</b></header><article v-for="(evidence, index) in selectedEdge.evidence" :key="index"><b>{{ evidence.locator || evidence.responsibility || `证据 ${Number(index) + 1}` }}</b><p>{{ evidence.excerpt || evidence.member_role || evidence.source_id }}</p></article></section>
        </template>
      </aside>
    </div>

    <footer class="graph-construction-status">
      <div><span>构建链路</span><b v-for="stage in graph.construction?.stages ?? []" :key="stage">{{ constructionStageLabels[stage] ?? stage }}</b></div>
      <p>{{ graph.construction?.source_count ?? 0 }} 个来源 · {{ graph.construction?.chunk_count ?? 0 }} 个片段 · {{ graph.construction?.concept_count ?? 0 }} 个知识实体 · {{ graph.construction?.evidence_edge_count ?? 0 }} 条证据关系</p>
    </footer>
  </section>
</template>

<style scoped>
.relationship-graph{overflow:hidden;border:4px solid #173a42;border-radius:17px;background:#132f38;color:#29464a;box-shadow:0 7px 0 #102d34}.graph-toolbar{display:grid;grid-template-columns:minmax(240px,1fr) minmax(260px,430px) auto;align-items:center;gap:12px;padding:12px 14px;background:#fff7df;border-bottom:3px solid #173a42}.graph-toolbar>div:first-child{display:flex;flex-direction:column}.graph-toolbar strong{font:900 12px 'Noto Serif SC'}.graph-toolbar small{margin-top:3px;color:#6b7770;font-size:8px}.graph-toolbar>label{display:flex;align-items:center;gap:7px;padding:8px 10px;border:2px solid #71857e;border-radius:11px;background:#fffdf3}.graph-toolbar>label svg{width:15px}.graph-toolbar input{min-width:0;width:100%;border:0;outline:0;background:transparent;font-size:9px}.graph-tool-actions{display:flex;align-items:center;gap:5px}.graph-tool-actions button{width:31px;height:31px;display:grid;place-items:center;border:2px solid #31534f;border-radius:9px;background:#fff;color:#31534f}.graph-tool-actions button svg{width:14px}.graph-tool-actions b{min-width:40px;text-align:center;font-size:8px}.graph-filters{display:flex;align-items:center;gap:12px;padding:8px 12px;border-bottom:2px solid #31515a;background:#1c424c;color:#d8eee9}.graph-filters>div{display:flex;align-items:center;gap:5px;flex-wrap:wrap}.graph-filters>div>span{margin-right:2px;color:#f0cf75;font-size:8px;font-weight:900}.graph-filters button{display:flex;align-items:center;gap:4px;padding:5px 8px;border:1px solid #78908f;border-radius:12px;background:#17353d;color:#afc9c5;font-size:7px}.graph-filters button.active{border-color:#f2d176;background:#fff2bf;color:#29464a}.graph-filters button i{width:8px;height:8px;border-radius:50%}.graph-filters button b{font-size:6px;opacity:.72}.graph-filters .reset-filter{margin-left:auto;border-color:#e5bd64;color:#f5d983}.graph-stage{position:relative;height:620px;overflow:hidden;touch-action:none;background-color:#e8edef;background-image:radial-gradient(#91a4a1 1.2px,transparent 1.2px);background-size:24px 24px;cursor:grab}.graph-stage:active{cursor:grabbing}.graph-stage svg{display:block;width:100%;height:100%}.graph-stage marker path{fill:#657b7c}.graph-edge{cursor:pointer;transition:opacity .18s}.edge-hit{fill:none;stroke:transparent;stroke-width:16}.edge-line{fill:none;stroke:#839797;stroke-width:1.8}.edge-line[data-type=contains]{stroke:#d2933e;stroke-width:2.4}.edge-line[data-type=member]{stroke:#3d986e}.edge-line[data-type=inherited_by],.edge-line[data-type=authorized]{stroke:#6c5ead;stroke-dasharray:6 4}.edge-line[data-type=describes]{stroke:#c74c70;stroke-width:2.2}.edge-line[data-type=mentions]{stroke:#dd7652;stroke-dasharray:3 3}.graph-edge.selected .edge-line{stroke:#e43d65;stroke-width:4}.edge-label{fill:#506464;font-size:8px;font-weight:800;paint-order:stroke;stroke:#f8fbfa;stroke-width:4px;stroke-linejoin:round;pointer-events:auto;cursor:pointer}.edge-label.selected{fill:#d52f5b;font-size:9px;stroke:#fff6d7;stroke-width:5px}.graph-node{cursor:pointer;transition:opacity .18s}.node-halo{fill:#fff;opacity:0;stroke:#e43d65;stroke-width:3}.graph-node:hover .node-halo,.graph-node.selected .node-halo{opacity:.85}.node-body{stroke-width:3;filter:url(#node-shadow)}.node-icon{fill:#fff;font-size:11px;font-weight:900;pointer-events:none}.node-label{fill:#203f42;font-size:9px;font-weight:900;paint-order:stroke;stroke:#f8fbfa;stroke-width:4px;stroke-linejoin:round;pointer-events:none}.node-subtitle{fill:#617579;font-size:7px;paint-order:stroke;stroke:#f8fbfa;stroke-width:3px;pointer-events:none}.graph-operation-hint{position:absolute;left:14px;bottom:12px;padding:7px 9px;border:2px solid #8aa09f;border-radius:9px;background:#fffdf1dd;color:#536865;font-size:7px;box-shadow:0 3px 0 #546b6b55}.graph-empty{position:absolute;inset:0;display:grid;place-content:center;text-align:center;pointer-events:none}.graph-empty span{font-size:48px;color:#9bafad}.graph-empty strong{font-size:12px}.graph-empty small{margin-top:5px;color:#71817f;font-size:8px}.graph-detail{position:absolute;right:14px;top:14px;width:min(340px,calc(100% - 28px));max-height:calc(100% - 28px);overflow:auto;padding:13px;border:3px solid #294d50;border-radius:14px;background:#fff9e8;box-shadow:6px 7px 0 #26464a66;cursor:default}.graph-detail>header{display:flex;align-items:flex-start;justify-content:space-between;gap:10px;padding-bottom:9px;border-bottom:2px dashed #ad9562}.graph-detail>header>div{display:flex;min-width:0;flex-direction:column}.graph-detail>header small{color:#8c623c;font-size:7px}.graph-detail>header strong{overflow:hidden;margin-top:3px;font-size:13px;text-overflow:ellipsis;white-space:nowrap}.graph-detail>header button{width:26px;height:26px;display:grid;place-items:center;border:0;border-radius:8px;background:#eadcba}.graph-detail>header button svg{width:13px}.detail-type{display:flex;align-items:center;gap:6px;margin:10px 0;padding:6px 8px;border:2px solid #80928b;border-radius:9px;background:#f4efd5;font-size:8px;font-weight:900}.detail-type i{width:10px;height:10px;border-radius:50%}.detail-type b{margin-left:auto;color:#69766f;font-size:7px}.graph-detail>p,.graph-detail blockquote{color:#52635e;font-size:8px;line-height:1.65}.graph-detail blockquote{margin:8px 0;padding:8px;border-left:3px solid #d95476;background:#f5e6d9}.graph-detail dl{margin:0}.graph-detail dl>div{display:grid;grid-template-columns:92px minmax(0,1fr);gap:7px;padding:5px 0;border-bottom:1px solid #e5ddc7}.graph-detail dt{color:#806d4c;font-size:7px}.graph-detail dd{margin:0;overflow-wrap:anywhere;font-size:8px}.graph-detail section{margin-top:11px;padding-top:9px;border-top:2px dashed #b3a176}.graph-detail section>header{display:flex;justify-content:space-between;margin-bottom:6px}.graph-detail section>header strong,.graph-detail section>header b{font-size:8px}.graph-detail section>button{width:100%;display:grid;grid-template-columns:62px minmax(0,1fr) auto;gap:6px;padding:7px;border:0;border-bottom:1px solid #e4ddc7;background:transparent;text-align:left}.graph-detail section>button span{color:#9b5e3b;font-size:7px}.graph-detail section>button b{overflow:hidden;font-size:8px;text-overflow:ellipsis;white-space:nowrap}.graph-detail section>button small{font-size:6px}.graph-detail section>article{padding:7px;border-radius:8px;background:#f0e8ce}.graph-detail section>article+article{margin-top:5px}.graph-detail section>article b{font-size:8px}.graph-detail section>article p{margin:3px 0 0;font-size:7px}.open-source{width:100%;margin-top:10px;padding:9px;border:2px solid #304e4c;border-radius:9px;background:#36a27d;color:#fff;font-size:8px;font-weight:900}.relation-route{display:grid;grid-template-columns:minmax(0,1fr) auto minmax(0,1fr);align-items:center;gap:6px;margin-top:11px}.relation-route button{padding:7px;border:2px solid #657c76;border-radius:8px;background:#eff0d7;font-size:8px}.relation-route span{color:#b14b62;font-size:7px;font-weight:900}.graph-construction-status{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:9px 12px;background:#fff7df;border-top:3px solid #173a42}.graph-construction-status>div{display:flex;align-items:center;gap:5px;flex-wrap:wrap}.graph-construction-status span{color:#8b623d;font-size:7px;font-weight:900}.graph-construction-status b{padding:3px 6px;border:1px solid #779087;border-radius:8px;background:#eef1dc;font-size:6px}.graph-construction-status p{margin:0;color:#60716a;font-size:7px}
@media(max-width:900px){.graph-toolbar{grid-template-columns:1fr}.graph-tool-actions{justify-content:flex-start}.graph-filters{align-items:flex-start;flex-direction:column}.graph-filters .reset-filter{margin-left:0}.graph-stage{height:560px}.graph-construction-status{align-items:flex-start;flex-direction:column}}
</style>
