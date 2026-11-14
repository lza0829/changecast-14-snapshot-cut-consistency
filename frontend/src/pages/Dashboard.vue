<script setup>
import { onMounted, ref } from 'vue'
import { getJSON } from '../api'
const stats = ref(null)
const err = ref('')
onMounted(async () => {
  try { stats.value = await getJSON('/api/dashboard') } catch (e) { err.value = String(e.message || e) }
})
</script>
<template>
  <div class="page">
    <h1>总览</h1>
    <p class="muted">变更日志投影：源 CDC 事件按序落到当前投影，批次计数与快照互证。</p>
    <p v-if="err" class="tag danger">{{ err }}</p>
    <div class="panel" v-if="stats">
      <div class="stat-grid">
        <div class="stat"><div class="stat-num">{{ stats.stream_count }}</div><div class="stat-label">投影流</div></div>
        <div class="stat"><div class="stat-num">{{ stats.enabled_streams }}</div><div class="stat-label">已启用</div></div>
        <div class="stat"><div class="stat-num">{{ stats.batch_count }}</div><div class="stat-label">应用批次</div></div>
        <div class="stat"><div class="stat-num">{{ stats.completed_cuts }}</div><div class="stat-label">已完成切面</div></div>
        <div class="stat"><div class="stat-num">{{ stats.projection_alive }}</div><div class="stat-label">存活投影</div></div>
        <div class="stat"><div class="stat-num">{{ stats.projection_deleted }}</div><div class="stat-label">已删投影</div></div>
        <div class="stat"><div class="stat-num">{{ stats.ooo_buffered }}</div><div class="stat-label">缓冲中</div></div>
      </div>
      <p style="margin-top:1rem">默认应用序 <span class="tag">{{ stats.apply_order }}</span>（按事件 seq 升序）</p>
      <p>切面互斥策略 <span class="tag">{{ stats.cut_policy }}</span>
        <span class="muted" style="font-size:0.86rem">
          （reject_apply = 拒绝应用开跑直至切面完成；snapshot_read = 允许应用，切面读单一已提交快照）
        </span>
      </p>
      <p><router-link to="/run">去投影台跑一趟 →</router-link> · <router-link to="/cuts">固化投影切面 →</router-link></p>
    </div>
  </div>
</template>
