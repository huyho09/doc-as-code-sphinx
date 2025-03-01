<template>
  <div class="container">
    <a-card title="Docs as Code - Sphinx Generator">
      <a-input v-model:value="repoUrl" placeholder="Enter public GitHub repository URL" />
      <a-button type="primary" @click="fetchSourceCode" :loading="loading" style="margin-top: 10px">
        Generate Documentation
      </a-button>

      <a-progress v-if="loading" :percent="progress" status="active" style="margin-top: 15px" />

      <a-alert v-if="message" :message="message" type="success" showIcon style="margin-top: 15px" />

      <a-button v-if="previewUrl" type="link" :href="previewUrl" target="_blank" style="margin-top: 10px">
        📖 Preview Documentation
      </a-button>
    </a-card>
  </div>
</template>

<script setup>
import { ref } from 'vue';
import axios from 'axios';

const repoUrl = ref('');
const loading = ref(false);
const progress = ref(0);
const message = ref('');
const previewUrl = ref('');

const fetchSourceCode = async () => {
  if (!repoUrl.value) {
    message.value = "Please enter a valid GitHub repository URL";
    return;
  }

  loading.value = true;
  progress.value = 20;

  try {
    const response = await axios.post('http://localhost:3000/generate-docs', { repoUrl: repoUrl.value });

    progress.value = 70;

    if (response.data.success) {
      message.value = "Documentation successfully generated!";
      previewUrl.value = response.data.previewUrl;
      progress.value = 100;
    } else {
      message.value = "Failed to generate documentation. Try again.";
      progress.value = 0;
    }
  } catch (error) {
    message.value = "Error processing the request.";
    console.error(error);
  } finally {
    loading.value = false;
  }
};
</script>

<style>
.container {
  max-width: 600px;
  margin: 50px auto;
  padding: 20px;
}
</style>
