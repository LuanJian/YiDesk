<template>

  <router-view />

</template>

<style>

* { box-sizing: border-box; }

/* body/html 深色背景（与侧边栏一致）——页面滑动溢出时底部不再露出浅色白条；内容区浅色由 .main 自带 */

html, body { background: #1d2535; overflow-x: hidden; }

html, body, #app { height: 100%; margin: 0; }

body {

  font-family: 'PingFang SC', 'Microsoft YaHei', 'Helvetica Neue', Arial, sans-serif;

  color: #303133;

}

/* 全站模块说明 el-alert 字号统一（title 13px / description 12px） */

.el-alert__title { font-size: 13px !important; }

.el-alert__description { font-size: 12px !important; line-height: 1.6; }

/* 日期范围选择框禁止 flex 拉伸——EP 的 .el-input__wrapper 自带 flex-grow:1 会命中

   daterange 根元素，导致日期框被 .toolbar/.filters 等弹性容器拉伸出大量留白（以 style.width 为准） */

.el-date-editor.el-input__wrapper.el-range-editor { flex-grow: 0; flex-shrink: 0; }

</style>
