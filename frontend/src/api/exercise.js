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
};
