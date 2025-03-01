<template>
  <div id="app">
    <h1>Generate Sphinx Documentation</h1>
    <RepoForm @generate-docs="handleGenerateDocs" />
    <div v-if="downloadLink">
      <p>Documentation generated successfully!</p>
      <a :href="downloadLink" target="_blank" download>Download RST File</a>
    </div>
  </div>
</template>

<script>
import RepoForm from './components/RepoForm.vue';

export default {
  name: 'App',
  components: { RepoForm },
  data() {
    return {
      downloadLink: null,
    };
  },
  methods: {
    handleGenerateDocs(link) {
      this.downloadLink = link;
    },
  },
};
</script>

<style>
#app {
  font-family: Arial, sans-serif;
  text-align: center;
  margin-top: 50px;
}
h1 {
  color: #2c3e50;
}
</style>