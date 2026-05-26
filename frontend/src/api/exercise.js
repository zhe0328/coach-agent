import client from "./client";

export const exerciseApi = {
    // FastAPI parses simple str params from query string on POST
    getAiRecommendation: async (sessionId, userId, message) => {
        try {
            const response = await client.post("/v1/chat/static", {
                session_id: sessionId,
                user_id: userId,
                message: message
            });
            // 返回后端合成的 CoachResponse 结构
            console.log("response got from backend: ", response)
            return response.data;
        } catch (error) {
            console.error("Coach API Error:", error);
            throw error;
        }
    },

    getExerciseDetail: (id) => client.get(`v1/exercises/${id}`),

    signup: async (payload) => {
        const response = await client.post('/v1/user/signup', payload);
        console.log("response signup: ", response);
        return response;
    },

    login: async (payload) => {
        try {
            const response = await client.post('/v1/user/login', payload);
            console.log("response login: ", response);
            return response;
        } catch (error) {
            console.error("Coach API Error:", error);
            throw error;
        }
    },

    updateProfile:  async (payload) => {
        const response = await client.post('/v1/user/profile/update', payload);
        console.log("response login: ", response)
        return response;
    },

    getProfile: (id) => client.get(`v1/user/profile/${id}`),

    getSessions: (user_id) => client.get(`v1/chat/sessions/${user_id}`),

    getSessionDetails: (session_id) => client.get(`v1/chat/history/${session_id}`)
};
