<script setup>
import { onMounted, ref } from 'vue'
import { getJSON } from '../api'
const rows = ref([])
const err = ref('')
onMounted(async () => {
  try { rows.value = await getJSON('/api/ooo-buffer') } catch (e) { err.value = String(e.message || e) }
})
</script>
<template>
  <div class="page">
    <h1>缓冲区</h1>
    <p class="muted">乱序/晚到事件缓冲表。底座空挂，窗内缓冲与逾窗策略留给后题。</p>
    <p v-if="err" class="tag danger">{{ err }}</p>
    <div class="panel">
      <table>
        <thead>
          <tr>
            <th>流</th><th>event_id</th><th>实体键</th><th>op</th><th>seq</th><th>状态</th><th>入缓时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in rows" :key="r.id">
            <td>{{ r.stream_id }}</td>
            <td class="mono">{{ r.event_id }}</td>
            <td class="mono">{{ r.entity_key }}</td>
            <td class="mono">{{ r.op }}</td>
            <td class="mono">{{ r.seq }}</td>
            <td><span class="tag warn">{{ r.status }}</span></td>
            <td class="mono">{{ r.buffered_at }}</td>
          </tr>
          <tr v-if="!rows.length"><td colspan="7" class="muted">当前无缓冲事件（底座默认按 seq 直接投影）。</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
