<script setup>
import { onMounted, ref } from 'vue'
import { getJSON } from '../api'
const rows = ref([])
const err = ref('')
onMounted(async () => {
  try { rows.value = await getJSON('/api/batches?limit=100') } catch (e) { err.value = String(e.message || e) }
})
</script>
<template>
  <div class="page">
    <h1>应用批次</h1>
    <p class="muted">每次投影应用落一批次：源事件数、写入/删除、存活/已删与水位 seq。</p>
    <p v-if="err" class="tag danger">{{ err }}</p>
    <div class="panel">
      <table>
        <thead>
          <tr>
            <th>批次</th><th>投影流</th><th>状态</th>
            <th>源事件</th><th>写入</th><th>删除</th><th>跳过</th>
            <th>存活</th><th>已删</th><th>max seq</th><th>时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="b in rows" :key="b.id">
            <td class="mono">{{ b.batch_no }}</td>
            <td>{{ b.stream_title }}</td>
            <td><span class="tag ok">{{ b.status }}</span></td>
            <td>{{ b.source_events }}</td>
            <td>{{ b.applied_upsert }}</td>
            <td>{{ b.applied_delete }}</td>
            <td>{{ b.skipped_duplicate }}</td>
            <td>{{ b.projected_alive }}</td>
            <td>{{ b.projected_deleted }}</td>
            <td class="mono">{{ b.max_seq }}</td>
            <td class="mono">{{ b.created_at }}</td>
          </tr>
          <tr v-if="!rows.length"><td colspan="11" class="muted">尚无批次。</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
