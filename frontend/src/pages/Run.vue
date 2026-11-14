<script setup>
import { onMounted, ref } from 'vue'
import { getJSON, postJSON } from '../api'

const streams = ref([])
const batches = ref([])
const streamId = ref(null)
const note = ref('')
const last = ref(null)
const busy = ref(false)
const err = ref('')
const upToSeq = ref(null)
const holdMs = ref(0)
const working = ref({ cut: null, apply: null })

async function refresh() {
  streams.value = await getJSON('/api/streams')
  batches.value = await getJSON('/api/batches?limit=20')
  if (streamId.value == null && streams.value.length) streamId.value = streams.value[0].id
  if (streamId.value != null) {
    working.value = await getJSON(`/api/concurrency?stream_id=${streamId.value}`)
  }
}

async function run() {
  err.value = ''
  busy.value = true
  try {
    const body = { stream_id: Number(streamId.value), note: note.value || null }
    if (upToSeq.value !== null && upToSeq.value !== '') body.up_to_seq = Number(upToSeq.value)
    if (Number(holdMs.value)) body.hold_ms = Number(holdMs.value)
    last.value = await postJSON('/api/project', body)
    await refresh()
  } catch (e) {
    err.value = String(e.message || e)
    await refresh()
  } finally {
    busy.value = false
  }
}

onMounted(async () => {
  try { await refresh() } catch (e) { err.value = String(e.message || e) }
})
</script>
<template>
  <div class="page">
    <h1>投影台</h1>
    <p class="muted">选一条投影流，读取 CDC 夹具并按 seq 应用到投影表。底座策略：按事件序投影，软删除留墓碑行。</p>
    <p v-if="err" class="tag danger">{{ err }}</p>

    <div class="panel">
      <h3 style="margin-top:0">发起投影</h3>
      <div style="display:flex;flex-wrap:wrap;gap:0.75rem;align-items:flex-end">
        <label>
          投影流
          <select v-model.number="streamId" style="display:block;min-width:18rem;margin-top:0.25rem">
            <option v-for="s in streams" :key="s.id" :value="s.id">{{ s.title }}</option>
          </select>
        </label>
        <label>
          备注（可选）
          <input v-model="note" style="display:block;width:12rem;margin-top:0.25rem" placeholder="本趟说明" />
        </label>
        <label>
          截到 seq（可选）
          <input v-model.number="upToSeq" type="number" min="0" placeholder="全部"
                 style="display:block;width:7rem;margin-top:0.25rem" />
        </label>
        <label>
          提交前停顿 ms
          <input v-model.number="holdMs" type="number" min="0" max="10000" step="100"
                 style="display:block;width:7rem;margin-top:0.25rem" />
        </label>
        <button :disabled="busy || !streamId" @click="run">{{ busy ? '投影中…' : '应用变更流' }}</button>
      </div>
      <p class="muted" style="margin:0.7rem 0 0;font-size:0.86rem">
        提交前停顿让批次处于「已写入未提交」状态，便于观察切面只读已提交快照。
      </p>
      <p v-if="working.cut" class="tag warn" style="margin-top:0.6rem">
        同流切面固化进行中（策略 {{ working.cut.policy }}）
        <template v-if="working.cut.policy === 'reject_apply'">，本次应用将被拒绝。</template>
        <template v-else>，本次应用可开跑，切面仍读单一已提交快照。</template>
      </p>
    </div>

    <div class="panel" v-if="last">
      <h3 style="margin-top:0">最近一趟</h3>
      <p>
        批次 <span class="mono">{{ last.batch_no }}</span> · {{ last.stream_title }} ·
        <span class="tag ok">{{ last.status }}</span>
      </p>
      <div class="stat-grid">
        <div class="stat"><div class="stat-num">{{ last.source_events }}</div><div class="stat-label">源事件</div></div>
        <div class="stat"><div class="stat-num">{{ last.applied_upsert }}</div><div class="stat-label">写入</div></div>
        <div class="stat"><div class="stat-num">{{ last.applied_delete }}</div><div class="stat-label">删除</div></div>
        <div class="stat"><div class="stat-num">{{ last.skipped_duplicate }}</div><div class="stat-label">跳过重复</div></div>
        <div class="stat"><div class="stat-num">{{ last.projected_alive }}</div><div class="stat-label">存活</div></div>
        <div class="stat"><div class="stat-num">{{ last.projected_deleted }}</div><div class="stat-label">已删</div></div>
        <div class="stat"><div class="stat-num">{{ last.max_seq }}</div><div class="stat-label">max seq（水位）</div></div>
      </div>
      <p style="margin-top:0.75rem">
        <router-link :to="{ path: '/projections', query: { stream_id: last.stream_id } }">查看投影快照 →</router-link>
        ·
        <router-link :to="{ path: '/events', query: { batch_id: last.id } }">事件留痕 →</router-link>
        ·
        <router-link :to="{ path: '/cuts', query: { stream_id: last.stream_id } }">固化切面 →</router-link>
      </p>
    </div>

    <div class="panel">
      <h3 style="margin-top:0">历史批次</h3>
      <table>
        <thead>
          <tr>
            <th>批次</th><th>投影流</th><th>状态</th>
            <th>源事件</th><th>写入</th><th>删除</th><th>存活</th><th>已删</th><th>时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="b in batches" :key="b.id">
            <td class="mono">{{ b.batch_no }}</td>
            <td>{{ b.stream_title }}</td>
            <td><span class="tag ok">{{ b.status }}</span></td>
            <td>{{ b.source_events }}</td>
            <td>{{ b.applied_upsert }}</td>
            <td>{{ b.applied_delete }}</td>
            <td>{{ b.projected_alive }}</td>
            <td>{{ b.projected_deleted }}</td>
            <td class="mono">{{ b.created_at }}</td>
          </tr>
          <tr v-if="!batches.length"><td colspan="9" class="muted">还没有批次，先跑一趟。</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
