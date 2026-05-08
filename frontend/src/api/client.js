import axios from "axios";

const client = axios.create({
  baseURL: "http://127.0.0.1:8000", // 你的 FastAPI 地址
  headers: {
    "Content-Type": "application/json",
  },
});

// 你可以在这里添加拦截器，例如处理 500 错误
client.interceptors.response.use(
  (response) => response.data,
  (error) => {
    console.error("API Error:", error.response?.data || error.message);
    return Promise.reject(error);
  },
);

export default client;
