<script setup lang="ts">
defineProps<{ items: Array<{ label: string; value: string }> }>()
const emit = defineEmits<{ (event: 'copy', value: string): void }>()
</script>

<template>
  <section class="connect-bar">
    <div v-for="item in items" :key="item.label" class="ci">
      <span class="ci-k">{{ item.label }}</span>
      <span class="ci-v mono ellipsis" :title="item.value">{{ item.value || '未设置' }}</span>
      <button class="ghost" @click="emit('copy', item.value)">复制</button>
    </div>
  </section>
</template>
