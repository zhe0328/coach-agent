import client from "./client";

export const exerciseApi = {
  // FastAPI parses simple str params from query string on POST
  getAiRecommendation: (message) =>
    client.post("/coach/chat", null, { params: { message } }),

  searchExercises: (params) => client.get("/exercises", { params }),

  getExerciseDetail: (id) => client.get(`/exercises/${id}`),
};
