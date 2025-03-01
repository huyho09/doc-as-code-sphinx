<template>
    <div class="repo-form">
      <input
        v-model="repoUrl"
        type="text"
        placeholder="Enter GitHub Repo URL (e.g., https://github.com/user/repo)"
        class="url-input"
      />
      <button @click="submitRepo" :disabled="!repoUrl || loading" class="submit-btn">
        {{ loading ? 'Generating...' : 'Submit' }}
      </button>
      <p v-if="error" class="error">{{ error }}</p>
    </div>
  </template>
  
  <script>
  import axios from 'axios';
  
  export default {
    name: 'RepoForm',
    data() {
      return {
        repoUrl: '',
        error: null,
        loading: false,
      };
    },
    methods: {
      async submitRepo() {
        this.error = null;
        this.loading = true;
        try {
          const response = await axios.post('http://localhost:3000/generate-docs', {
            repoUrl: this.repoUrl,
          });
          this.$emit('generate-docs', response.data.downloadLink);
          this.repoUrl = '';
        } catch (error) {
          this.error = 'Failed to generate docs. Check the URL or try again.';
          console.error(error);
        } finally {
          this.loading = false;
        }
      },
    },
  };
  </script>
  
  <style scoped>
  .repo-form {
    margin: 20px 0;
  }
  .url-input {
    width: 300px;
    padding: 10px;
    font-size: 16px;
    border: 1px solid #ccc;
    border-radius: 4px;
  }
  .submit-btn {
    padding: 10px 20px;
    margin-left: 10px;
    background-color: #42b983;
    color: white;
    border: none;
    border-radius: 4px;
    cursor: pointer;
  }
  .submit-btn:disabled {
    background-color: #cccccc;
    cursor: not-allowed;
  }
  .error {
    color: red;
    margin-top: 10px;
  }
  </style>