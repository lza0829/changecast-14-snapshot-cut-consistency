<script setup>
import { onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { getJSON } from '../api'

const route = useRoute()
const rows = ref([])
const streams = ref([])
const streamId = ref(null)
const includeDeleted = ref(true)
const err = ref('')

async function refresh() {
  const q = new URLSearchParams()
  if (streamId.value) q.set('stream_id', String(streamId.value))
  q.set('include_deleted', includeDeleted.value ? 'true' : 'false')
  rows.value = await getJSON('/api/projections?' + q.toString())
}

onMounted(async () => {
  try {
    streams.value = await getJSON('/api/streams')
    if (route.query.stream_id) streamId.value = Number(route.query.stream_id)
    await refresh()
  } catch (e) {
    err.value = String(e.message || e)
  }
})

watch([streamId, includeDeleted], async () => {
  try { await refresh() } catch (e) { err.value = String(e.message || e) }
})
</script>
<template>
  <div class="page">
    <h1>投影快照</h1>
    <p class="muted">当前投影行：实体键、最近应用 seq、载荷与删除态。与批次计数互证。</p>
    <p v-if="err" class="tag danger">{{ err }}</p>
    <div class="panel" style="display:flex;flex-wrap:wrap;gap:0.75rem;align-items:flex-end">
      <label>
        投影流
        <select v-model="streamId" style="display:block;min-width:14rem;margin-top:0.25rem">
          <option :value="undefined">全部</option>
          <option v-for="s in streams" :key="s.id" :value="s.id">{{ s.title }}</option>
        </select>
      </label>
      <label style="display:flex;align-items:center;gap:0.4rem;margin-bottom:0.15rem">
        <input type="checkbox" v-model="includeDeleted" />
        含已删墓碑
      </label>
    </div>
    <div class="panel">
      <table>
        <thead>
          <tr>
            <th>流</th><th>实体键</th><th>seq</th><th>事件</th><th>状态</th><th>载荷</th><th>更新时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in rows" :key="r.id">
            <td>{{ r.stream_title }}</td>
            <td class="mono">{{ r.entity_key }}</td>
            <td class="mono">{{ r.applied_seq }}</td>
            <td class="mono">{{ r.applied_event_id }}</td>
            <td>
              <span class="tag" :class="r.deleted ? 'danger' : 'ok'">{{ r.deleted ? '已删' : '存活' }}</span>
            </td>
            <td class="mono">{{ r.payload == null ? '—' : JSON.stringify(r.payload) }}</td>
            <td class="mono">{{ r.updated_at }}</td>
          </tr>
          <tr v-if="!rows.length"><td colspan="7" class="muted">暂无投影，先去投影台跑一趟。</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
