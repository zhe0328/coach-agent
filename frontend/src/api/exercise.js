import client from "./client";

const API_BASE = client.defaults.baseURL || "http://127.0.0.1:8000";

function parseSseChunk(buffer) {
  const events = [];
  const parts = buffer.split("\n\n");
  const remainder = parts.pop() ?? "";

  for (const part of parts) {
    const line = part
      .split("\n")
      .find((l) => l.startsWith("data: "));
    if (!line) continue;
    const payload = line.slice(6).trim();
    if (payload === "[DONE]") {
      events.push({ type: "done_signal" });
      continue;
    }
    try {
      events.push(JSON.parse(payload));
    } catch {
      /* ignore malformed frames */
    }
  }

  return { events, remainder };
}

export const exerciseApi = {
  streamChat: async (
    sessionId,
    userId,
    message,
    { onStatus, onChunk, onMetadata, onDone, onError } = {},
  ) => {
    const token = localStorage.getItem("access_token");
    const response = await fetch(`${API_BASE}/v1/chat`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({
        session_id: sessionId,
        user_id: userId,
        message,
      }),
    });

    if (!response.ok) {
      const err = new Error(`Chat stream failed: ${response.status}`);
      err.status = response.status;
      if (onError) onError(err);
      throw err;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const { events, remainder } = parseSseChunk(buffer);
      buffer = remainder;

      for (const event of events) {
        if (event.type === "done_signal") continue;
        if (event.type === "error") {
          if (onError) onError(event);
          throw new Error(event.detail || "Stream error");
        }
        if (event.type === "status" && onStatus) onStatus(event);
        if (event.type === "chunk" && onChunk) onChunk(event.content);
        if (event.type === "metadata" && onMetadata) onMetadata(event.data);
        if (event.type === "done" && onDone) onDone(event.data);
      }
    }
  },

  getAiRecommendation: async (sessionId, userId, message) => {
    try {
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

  /** Fire-and-forget: preload Neo4j semantic profile into Redis after login. */
  warmupUserContext: async () => {
    const token = localStorage.getItem("access_token");
    if (!token) return;
    try {
      await fetch(`${API_BASE}/v1/user/warmup`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });
    } catch (error) {
      console.warn("User context warmup failed:", error);
    }
  },
};
