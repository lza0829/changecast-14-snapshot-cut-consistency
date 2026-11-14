<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { getJSON, postJSON } from '../api'

const route = useRoute()

const streams = ref([])
const cuts = ref([])
const bindings = ref([])
const streamId = ref(null)
const bindMode = ref('watermark')
const watermarkInput = ref(0)
const batchNoInput = ref('')
const policy = ref('')
const holdMs = ref(0)
const note = ref('')

const busy = ref(false)
const err = ref('')
const flash = ref('')
const detail = ref(null)
const verify = ref(null)

const stream = computed(() => streams.value.find((s) => s.id === streamId.value) || null)
const latestBatch = computed(() => bindings.value[0] || null)
const workingState = ref({ cut: null, apply: null })
const settings = ref({})

async function refreshBase() {
  streams.value = await getJSON('/api/streams')
  settings.value = await getJSON('/api/settings')
  if (streamId.value == null && streams.value.length) {
    const q = Number(route.query.stream_id)
    streamId.value = q || streams.value[0].id
  }
  await refreshStream()
}

async function refreshStream() {
  if (streamId.value == null) return
  cuts.value = await getJSON(`/api/cuts?stream_id=${streamId.value}&limit=50`)
  bindings.value = await getJSON('/api/batches?limit=50')
  workingState.value = await getJSON(`/api/concurrency?stream_id=${streamId.value}`)
  if (bindMode.value === 'watermark' && !watermarkInput.value) {
    watermarkInput.value = stream.value ? stream.value.watermark_seq : 0
  }
}

function pickBatch(b) {
  batchNoInput.value = b.batch_no
  bindMode.value = 'batch'
}

async function takeCut() {
  err.value = ''
  flash.value = ''
  busy.value = true
  try {
    const body = {
      stream_id: Number(streamId.value),
      policy: policy.value || null,
      hold_ms: Number(holdMs.value) || 0,
      note: note.value || null,
    }
    if (bindMode.value === 'watermark') body.watermark_seq = Number(watermarkInput.value)
    else body.batch_no = batchNoInput.value
    detail.value = await postJSON('/api/cuts', body)
    verify.value = await getJSON(`/api/cuts/${detail.value.id}/verify`)
    flash.value = `切面 ${detail.value.cut_no} 已固化`
    await refreshStream()
  } catch (e) {
    err.value = String(e.message || e)
    await refreshStream()
  } finally {
    busy.value = false
  }
}

async function openCut(id) {
  err.value = ''
  try {
    detail.value = await getJSON(`/api/cuts/${id}`)
    verify.value = await getJSON(`/api/cuts/${id}/verify`)
  } catch (e) {
    err.value = String(e.message || e)
  }
}

async function reVerify() {
  if (!detail.value) return
  try {
    verify.value = await getJSON(`/api/cuts/${detail.value.id}/verify`)
  } catch (e) {
    err.value = String(e.message || e)
  }
}

watch(streamId, async () => {
  detail.value = null
  verify.value = null
  watermarkInput.value = 0
  try { await refreshStream() } catch (e) { err.value = String(e.message || e) }
})

onMounted(async () => {
  try { await refreshBase() } catch (e) { err.value = String(e.message || e) }
})
</script>

<template>
<div class="page">
  <h1>投影切面</h1>
  <p class="muted">
    固化一个绑定明确水位（或已成功批次号）的投影切面。切面行集合必须与该水位下的投影一致，
    并记录实体键、applied_seq、删除态与载荷摘要；行数与存活/已删须与绑定水位查询一致。
  </p>
  <p v-if="err" class="tag danger">{{ err }}</p>
  <p v-if="flash" class="tag ok">{{ flash }}</p>

  <div class="panel">
    <h3 style="margin-top:0">发起固化</h3>
    <div style="display:flex;flex-wrap:wrap;gap:0.75rem;align-items:flex-end">
      <label>
        投影流
        <select v-model.number="streamId" style="display:block;min-width:16rem;margin-top:0.25rem">
          <option v-for="s in streams" :key="s.id" :value="s.id">{{ s.title }}</option>
        </select>
      </label>
      <label>
        绑定方式
        <select v-model="bindMode" style="display:block;margin-top:0.25rem">
          <option value="watermark">明确水位 seq</option>
          <option value="batch">已成功批次号</option>
        </select>
      </label>
      <label v-if="bindMode === 'watermark'">
        水位 seq
        <input v-model.number="watermarkInput" type="number" min="0"
               style="display:block;width:8rem;margin-top:0.25rem" />
      </label>
      <label v-else>
        批次号
        <input v-model="batchNoInput" class="mono"
               style="display:block;width:15rem;margin-top:0.25rem"
               :placeholder="latestBatch ? latestBatch.batch_no : 'PB-YYYYMMDD-NNNN'" />
      </label>
      <label>
        并发策略
        <select v-model="policy" style="display:block;min-width:15rem;margin-top:0.25rem">
          <option value="">跟随设置（{{ settings.cut_policy || 'reject_apply' }}）</option>
          <option value="reject_apply">拒绝应用开跑直至切面完成</option>
          <option value="snapshot_read">允许应用，切面读单一已提交快照</option>
        </select>
      </label>
      <label>
        固化停顿 ms（演示并发）
        <input v-model.number="holdMs" type="number" min="0" max="10000" step="100"
               style="display:block;width:8rem;margin-top:0.25rem" />
      </label>
      <label>
        备注
        <input v-model="note" style="display:block;width:12rem;margin-top:0.25rem" placeholder="可选" />
      </label>
      <button :disabled="busy || !streamId" @click="takeCut">{{ busy ? '固化中…' : '固化切面' }}</button>
    </div>
    <p class="muted" style="margin:0.75rem 0 0;font-size:0.86rem">
      当前已提交水位 <span class="mono">{{ stream ? stream.watermark_seq : '—' }}</span>。
      绑定水位超过已提交水位将拒绝固化（无法证明该时刻）。
    </p>
  </div>

  <div class="panel">
    <h3 style="margin-top:0">同流并发状态</h3>
    <p class="muted" style="margin-top:0">
      固化进行中，同流常规应用按所选策略互斥：拒绝开跑，或允许开跑但切面只读单一已提交快照点。
    </p>
    <table>
      <thead><tr><th>进行中操作</th><th>策略</th><th>状态</th><th>起始</th><th>到期</th></tr></thead>
      <tbody>
        <tr v-if="workingState.cut">
          <td><span class="tag warn">切面固化</span> <span class="mono">{{ workingState.cut.token }}</span></td>
          <td class="mono">{{ workingState.cut.policy }}</td>
          <td>{{ workingState.cut.status }}</td>
          <td class="mono">{{ workingState.cut.started_at }}</td>
          <td class="mono">{{ workingState.cut.expires_at }}</td>
        </tr>
        <tr v-if="workingState.apply">
          <td><span class="tag warn">常规应用</span> <span class="mono">{{ workingState.apply.token }}</span></td>
          <td class="mono">—</td>
          <td>{{ workingState.apply.status }}</td>
          <td class="mono">{{ workingState.apply.started_at }}</td>
          <td class="mono">{{ workingState.apply.expires_at }}</td>
        </tr>
        <tr v-if="!workingState.cut && !workingState.apply">
          <td colspan="5" class="muted">同流当前无进行中的固化或应用。</td>
        </tr>
      </tbody>
    </table>
  </div>

  <div class="panel" v-if="detail">
    <h3 style="margin-top:0">
      切面 <span class="mono">{{ detail.cut_no }}</span>
      <span class="tag" :class="detail.status === 'completed' ? 'ok' : 'danger'" style="margin-left:0.4rem">{{ detail.status }}</span>
    </h3>
    <div class="stat-grid">
      <div class="stat"><div class="stat-num">{{ detail.row_count }}</div><div class="stat-label">行数</div></div>
      <div class="stat"><div class="stat-num">{{ detail.alive_count }}</div><div class="stat-label">存活</div></div>
      <div class="stat"><div class="stat-num">{{ detail.deleted_count }}</div><div class="stat-label">已删</div></div>
      <div class="stat"><div class="stat-num">{{ detail.bound_watermark_seq }}</div><div class="stat-label">绑定水位</div></div>
      <div class="stat"><div class="stat-num">{{ detail.snapshot_watermark_seq == null ? '—' : detail.snapshot_watermark_seq }}</div><div class="stat-label">快照读点水位</div></div>
      <div class="stat"><div class="stat-num mono" style="font-size:1rem">{{ detail.bind_type }}</div><div class="stat-label">绑定方式</div></div>
    </div>
    <p class="muted" style="font-size:0.86rem">
      绑定：<span class="mono">{{ detail.bind_type === 'batch' ? detail.bind_batch_no : ('水位 ' + detail.bound_watermark_seq) }}</span>
      · 读模式 <span class="mono">{{ detail.read_mode }}</span>
      · 互斥策略 <span class="mono">{{ detail.policy }}</span>
      · 校验方式 <span class="mono">{{ detail.verify_method || '—' }}</span>
      <span v-if="detail.failure_reason">· <span class="tag danger">{{ detail.failure_reason }}</span></span>
    </p>

    <div v-if="verify" class="panel" style="margin:0.6rem 0 0;border-left-color:var(--ok)">
      <h3 style="margin-top:0">核验</h3>
      <p>
        <span class="tag" :class="verify.ok ? 'ok' : 'danger'">{{ verify.ok ? '一致' : '不一致' }}</span>
        <span v-if="verify.reason" class="muted"> {{ verify.reason }}</span>
      </p>
      <table v-if="verify.replay">
        <thead><tr><th>口径</th><th>行数</th><th>存活</th><th>已删</th><th>水位</th></tr></thead>
        <tbody>
          <tr>
            <td>切面记录</td>
            <td>{{ verify.recorded.row_count }}</td>
            <td>{{ verify.recorded.alive_count }}</td>
            <td>{{ verify.recorded.deleted_count }}</td>
            <td class="mono">{{ detail.bound_watermark_seq }}</td>
          </tr>
          <tr>
            <td>按水位重放</td>
            <td>{{ verify.replay.row_count }}</td>
            <td>{{ verify.replay.alive_count }}</td>
            <td>{{ verify.replay.deleted_count }}</td>
            <td class="mono">{{ verify.replay.watermark_seq }}</td>
          </tr>
        </tbody>
      </table>
      <p v-if="verify.mismatched_entity_keys && verify.mismatched_entity_keys.length" class="muted">
        不一致实体键：<span class="mono">{{ verify.mismatched_entity_keys.join(', ') }}</span>
      </p>
      <p class="muted" style="font-size:0.86rem">核验时已提交水位 <span class="mono">{{ verify.committed_watermark_now }}</span>。</p>
      <button style="margin-top:0.4rem" @click="reVerify">重新核验</button>
    </div>

    <table style="margin-top:0.75rem">
      <thead><tr><th>实体键</th><th>applied_seq</th><th>状态</th><th>载荷摘要 (sha256)</th></tr></thead>
      <tbody>
        <tr v-for="r in detail.rows" :key="r.id">
          <td class="mono">{{ r.entity_key }}</td>
          <td class="mono">{{ r.applied_seq }}</td>
          <td><span class="tag" :class="r.deleted ? 'danger' : 'ok'">{{ r.deleted ? '已删' : '存活' }}</span></td>
          <td class="mono">{{ r.payload_digest.slice(0, 24) }}…</td>
        </tr>
        <tr v-if="!detail.rows || !detail.rows.length">
          <td colspan="4" class="muted">该切面没有行。</td>
        </tr>
      </tbody>
    </table>
  </div>

  <div class="panel">
    <h3 style="margin-top:0">切面历史</h3>
    <table>
      <thead>
        <tr>
          <th>切面</th><th>状态</th><th>绑定</th><th>绑定水位</th><th>快照读点</th>
          <th>行数</th><th>存活</th><th>已删</th><th>策略</th><th>时间</th><th></th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="c in cuts" :key="c.id">
          <td class="mono">{{ c.cut_no }}</td>
          <td><span class="tag" :class="c.status === 'completed' ? 'ok' : 'danger'">{{ c.status }}</span></td>
          <td class="mono">{{ c.bind_type === 'batch' ? c.bind_batch_no : 'watermark' }}</td>
          <td class="mono">{{ c.bound_watermark_seq }}</td>
          <td class="mono">{{ c.snapshot_watermark_seq == null ? '—' : c.snapshot_watermark_seq }}</td>
          <td>{{ c.row_count }}</td>
          <td>{{ c.alive_count }}</td>
          <td>{{ c.deleted_count }}</td>
          <td class="mono">{{ c.policy }}</td>
          <td class="mono">{{ c.finished_at }}</td>
          <td><button style="padding:0.2rem 0.5rem;font-size:0.82rem" @click="openCut(c.id)">查看</button></td>
        </tr>
        <tr v-if="!cuts.length"><td colspan="11" class="muted">尚无切面。选择水位或批次号发起固化。</td></tr>
      </tbody>
    </table>
  </div>

  <div class="panel" v-if="bindings.length">
    <h3 style="margin-top:0">可选的成功批次</h3>
    <p class="muted" style="margin-top:0">点选批次即可把切面绑定到该已成功批次（以其 max seq 为水位）。</p>
    <table>
      <thead><tr><th>批次</th><th>状态</th><th>max seq</th><th>存活</th><th>已删</th><th></th></tr></thead>
      <tbody>
        <tr v-for="b in bindings.filter((x) => x.status === 'completed').slice(0, 8)" :key="b.id">
          <td class="mono">{{ b.batch_no }}</td>
          <td><span class="tag ok">{{ b.status }}</span></td>
          <td class="mono">{{ b.max_seq }}</td>
          <td>{{ b.projected_alive }}</td>
          <td>{{ b.projected_deleted }}</td>
          <td><button style="padding:0.2rem 0.5rem;font-size:0.82rem" @click="pickBatch(b)">绑定此批次</button></td>
        </tr>
      </tbody>
    </table>
  </div>
</div>
</template>
