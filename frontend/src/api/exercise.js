import client from "./client";

export const exerciseApi = {
  getAiRecommendation: async (sessionId, userId, message) => {
    try {
      // client 拦截器已返回 axios 的 response.data，即 { data: CoachResponse }
      const response = await client.post("/v1/chat/static", {
        session_id: sessionId,
        user_id: userId,
        message: message,
      });
      return response?.data ?? response;
    } catch (error) {
      console.error("Coach API Error:", error);
      throw error;
    }
  },

  getExerciseDetail: (id) => client.get(`v1/exercises/${id}`),

  signup: async (payload) => {
    const response = await client.post("/v1/user/signup", payload);
    return response;
  },

  login: async (payload) => {
    try {
      const response = await client.post("/v1/user/login", payload);
      return response;
    } catch (error) {
      console.error("Coach API Error:", error);
      throw error;
    }
  },

  updateProfile: async (payload) => {
    const response = await client.post("/v1/user/profile/update", payload);
    return response;
  },

  getProfile: (id) => client.get(`v1/user/profile/${id}`),

  getSessions: (user_id) => client.get(`v1/chat/sessions/${user_id}`),

  getSessionDetails: (session_id) =>
    client.get(`v1/chat/history/${session_id}`),
};
