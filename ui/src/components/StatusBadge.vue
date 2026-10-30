<script setup lang="ts">
defineProps<{ text: string; kind?: 'good' | 'warn' | 'bad' }>()
</script>

<template>
  <span class="badge" :class="kind">{{ text }}</span>
</template>
