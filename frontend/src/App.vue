<template>
  <div class="container">
    <a-input v-model:value="repoUrl" placeholder="Enter GitHub Repository URL" />
    <a-button type="primary" @click="submitRepo" :loading="loading">Submit</a-button>
    <a-alert v-if="downloadLink" :message="'Download: ' + downloadLink" type="success" />
  </div>
</template>

<script setup>
import { ref } from 'vue';
import axios from 'axios';

const repoUrl = ref('');
const loading = ref(false);
const downloadLink = ref('');

const submitRepo = async () => {
  try {
    const response = await axios.post("http://localhost:5000/generate-docs",
      { repoUrl: "https://github.com/example/repo" }, 
      { withCredentials: true }  // ✅ Include credentials if needed
    );
    console.log("API Response:", response.data);
  } catch (error) {
    console.error("API Error:", error);
  }
};
</script>

<style scoped>
.container {
  max-width: 400px;
  margin: 100px auto;
  text-align: center;
}
</style>
