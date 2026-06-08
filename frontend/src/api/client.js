import axios from "axios";
import { triggerUnauthorized } from "./authSession";

const client = axios.create({
  baseURL: "http://127.0.0.1:8000",
  headers: {
    "Content-Type": "application/json",
  },
});

client.interceptors.request.use((config) => {
  const token = localStorage.getItem("access_token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// 你可以在这里添加拦截器，例如处理 500 错误
client.interceptors.response.use(
  (response) => response.data,
  (error) => {
    if (error.response?.status === 401) {
      triggerUnauthorized();
    }
    console.error("API Error:", error.response?.data || error.message);
    return Promise.reject(error);
  },
);

export default client;
