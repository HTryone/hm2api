<script setup lang="ts">
defineProps<{ title: string; hint?: string }>()
</script>

<template>
  <section class="panel">
    <header>
      <h2>{{ title }}</h2>
      <span v-if="hint" class="hint">{{ hint }}</span>
    </header>
    <slot />
  </section>
</template>
