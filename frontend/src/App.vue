<template>
  <div class="shell">
    <header class="topbar">
      <div class="brand-block">
        <div class="brand-mark" aria-hidden="true"></div>
        <div class="brand-text">
          <span class="brand-cn">变投影</span>
          <span class="brand-en">Changecast</span>
        </div>
      </div>
      <nav class="nav">
        <router-link to="/">总览</router-link>
        <router-link to="/streams">投影流</router-link>
        <router-link to="/run">投影台</router-link>
        <router-link to="/projections">投影快照</router-link>
        <router-link to="/batches">应用批次</router-link>
        <router-link to="/events">事件留痕</router-link>
        <router-link to="/buffer">缓冲区</router-link>
        <router-link to="/settings">设置</router-link>
      </nav>
    </header>
    <div class="stream-band" aria-hidden="true"></div>
    <main class="content">
      <router-view />
    </main>
  </div>
</template>
