<template>
  <XiaozhiAssistant
    assistant-name="罗伯特"
    variant="robert"
    :robot-image="robotImage"
    session-key="learnmate_robert_group"
  />
</template>

<script setup>
import XiaozhiAssistant from './XiaozhiAssistant.vue'
import robotImage from './robert-robot.png'
</script>
