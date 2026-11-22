<template>

  <!-- v2.12 设备管理：办公电脑 / 打印机 / 网络设备 三页签（设备信息登记，非资产管理） -->

  <div>

    <el-tabs v-model="tab" class="device-tabs">

      <el-tab-pane label="打印机" name="printer" lazy>

        <AssetView :only-categories="['打印机']" default-category="打印机" />

      </el-tab-pane>

      <el-tab-pane label="办公电脑" name="pc" lazy>

        <AssetView :only-categories="PC_CATEGORIES" default-category="电脑" />

      </el-tab-pane>

      <el-tab-pane label="网络设备" name="network" lazy>

        <NetworkDeviceView />

      </el-tab-pane>

    </el-tabs>

  </div>

</template>

<script setup lang="ts">

import { ref } from 'vue'

import AssetView from './AssetView.vue'

import NetworkDeviceView from './NetworkDeviceView.vue'

const PC_CATEGORIES = ['电脑', '显示器', '外设', '其他']

const tab = ref<'printer' | 'pc' | 'network'>('printer')

</script>

<style scoped>

.device-tabs :deep(.el-tabs__header) { margin-bottom: 14px; }

</style>
