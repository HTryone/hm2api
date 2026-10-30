<script setup lang="ts">
defineProps<{ items: Array<{ label: string; value: string }> }>()
</script>

<template>
  <div class="stats">
    <section v-for="item in items" :key="item.label" class="stat">
      <span>{{ item.label }}</span>
      <strong>{{ item.value }}</strong>
    </section>
  </div>
</template>
