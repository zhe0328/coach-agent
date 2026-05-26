import { useState, useRef, useEffect, useCallback } from "react";
import ChatMessage from "./ChatMessage";
import ChatInput from "./ChatInput";
import NewSessionButton from "./NewSessionButton";
import { exerciseApi } from "../api/exercise";

const WELCOME = {
  id: "welcome",
  role: "coach",
  content: {
    greeting: "你好！我是你的专业级 AI 健身教练。",
    detailed_guidance:
      "我已经同步加载了你在 Neo4j 中的长效解剖学受损关节防线。请直接告诉我你今天的训练目标！",
    response_type: "knowledge",
    safety_alerts: [],
    exercises: [],
  },
};

const ERROR_RESPONSE = {
  greeting: "链路发生异常...",
  detailed_guidance:
    "服务器管线断裂，原因极可能是后端自愈重试三次后触及最高安全硬性拦截死锁，请检查后台日志。",
  response_type: "knowledge",
  safety_alerts: ["系统级异常防御触发"],
  exercises: [],
};

function normalizeHistoryRecord(row) {
  const role = row.role === "assistant" ? "coach" : "user";

  if (role === "user") {
    return { id: row.id, role, content: row.content };
  }

  try {
    const parsed = JSON.parse(row.content);
    if (parsed && typeof parsed === "object" && parsed.detailed_guidance !== undefined) {
      return { id: row.id, role, content: parsed };
    }
  } catch {
    /* fall through — plain text from DB */
  }

  return {
    id: row.id,
    role: "coach",
    content: {
      greeting: "",
      detailed_guidance: row.content,
      response_type: "knowledge",
      safety_alerts: [],
      exercises: [],
    },
  };
}

function TypingIndicator() {
  return (
    <div className="message coach">
      <div className="message-bubble typing-bubble">
        <div className="typing-indicator">
          <span />
          <span />
          <span />
        </div>
      </div>
    </div>
  );
}

export default function ChatDashboard({ userId }) {
  const [sessions, setSessions] = useState([]);
  const [currentSessionId, setCurrentSessionId] = useState(
    () => localStorage.getItem("current_fitness_session_id") || null,
  );
  const [messages, setMessages] = useState([WELCOME]);
  const [isLoading, setIsLoading] = useState(false);
  const [sessionsLoading, setSessionsLoading] = useState(true);
  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isLoading]);

  const ensureSessionId = useCallback(() => {
    let sessionId = localStorage.getItem("current_fitness_session_id");
    if (!sessionId) {
      sessionId = crypto.randomUUID();
      localStorage.setItem("current_fitness_session_id", sessionId);
    }
    return sessionId;
  }, []);

  const loadSessions = useCallback(async () => {
    setSessionsLoading(true);
    try {
      const data = await exerciseApi.getSessions(userId);
      setSessions(Array.isArray(data) ? data : []);
    } catch {
      setSessions([]);
    } finally {
      setSessionsLoading(false);
    }
  }, [userId]);

  useEffect(() => {
    loadSessions();
  }, [loadSessions]);

  useEffect(() => {
    if (sessionsLoading) return;

    const storedId = localStorage.getItem("current_fitness_session_id");
    if (storedId) {
      setCurrentSessionId(storedId);
      return;
    }

    if (sessions.length > 0) {
      const latestId = sessions[0].session_id;
      localStorage.setItem("current_fitness_session_id", latestId);
      setCurrentSessionId(latestId);
      return;
    }

    const newId = ensureSessionId();
    setCurrentSessionId(newId);
  }, [sessions, sessionsLoading, ensureSessionId]);

  useEffect(() => {
    if (!currentSessionId) return;

    localStorage.setItem("current_fitness_session_id", currentSessionId);

    async function loadHistory() {
      try {
        const rows = await exerciseApi.getSessionDetails(currentSessionId);
        if (Array.isArray(rows) && rows.length > 0) {
          setMessages(rows.map(normalizeHistoryRecord));
        } else {
          setMessages([WELCOME]);
        }
      } catch {
        setMessages([WELCOME]);
      }
    }

    loadHistory();
  }, [currentSessionId]);

  const handleSessionSelect = (sessionId) => {
    if (sessionId === currentSessionId) return;
    setCurrentSessionId(sessionId);
  };

  const handleNewSession = (newSessionId) => {
    setCurrentSessionId(newSessionId);
    setMessages([WELCOME]);
    setSessions((prev) => [
      {
        session_id: newSessionId,
        last_message: "新对话…",
        created_at: new Date().toLocaleString("zh-CN", {
          month: "2-digit",
          day: "2-digit",
          hour: "2-digit",
          minute: "2-digit",
        }),
      },
      ...prev.filter((s) => s.session_id !== newSessionId),
    ]);
  };

  const sendMessage = async (text) => {
    if (!text.trim() || isLoading) return;

    const sessionId = currentSessionId || ensureSessionId();
    if (!currentSessionId) {
      setCurrentSessionId(sessionId);
    }

    const userMsg = { id: Date.now(), role: "user", content: text };
    setMessages((prev) => [...prev, userMsg]);
    setIsLoading(true);

    try {
      const responseStr = await exerciseApi.getAiRecommendation(
        sessionId,
        userId,
        text,
      );

      let payload;
      try {
        payload =
          typeof responseStr === "string" ? JSON.parse(responseStr) : responseStr;
      } catch {
        throw new Error("后端返回的 CoachResponse 结构体破损");
      }

      const data = payload?.data ?? payload;

      const coachMsg = {
        id: Date.now() + 1,
        role: "coach",
        content: data,
      };

      setMessages((prev) => [...prev, coachMsg]);

      setSessions((prev) => {
        const preview = text.slice(0, 20) + (text.length > 20 ? "…" : "");
        const stamp = new Date().toLocaleString("zh-CN", {
          month: "2-digit",
          day: "2-digit",
          hour: "2-digit",
          minute: "2-digit",
        });
        const existing = prev.filter((s) => s.session_id !== sessionId);
        return [
          { session_id: sessionId, last_message: preview, created_at: stamp },
          ...existing,
        ];
      });
    } catch (error) {
      console.error("Chat Error:", error);
      setMessages((prev) => [
        ...prev,
        {
          id: Date.now() + 1,
          role: "coach",
          content: ERROR_RESPONSE,
        },
      ]);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="chat-dashboard">
      <aside className="chat-sidebar">
        <div className="sidebar-header">
          <h3 className="sidebar-title">历史执教方案</h3>
          <NewSessionButton onSessionReset={handleNewSession} />
        </div>

        <div className="session-list">
          {sessionsLoading && (
            <p className="sidebar-empty">加载会话中…</p>
          )}
          {!sessionsLoading && sessions.length === 0 && (
            <p className="sidebar-empty">暂无历史，发送消息开始对话</p>
          )}
          {sessions.map((session) => (
            <button
              key={session.session_id}
              type="button"
              className={`session-item${
                currentSessionId === session.session_id ? " session-item--active" : ""
              }`}
              onClick={() => handleSessionSelect(session.session_id)}
            >
              <span className="session-time">
                {session.created_at || session.updated_at}
              </span>
              <span className="session-preview">{session.last_message}</span>
            </button>
          ))}
        </div>
      </aside>

      <div className="chat-main">
        <div className="chat-main-header">
          <span className="chat-main-label">当前会话</span>
          <code className="chat-session-id">{currentSessionId || "—"}</code>
        </div>

        <div className="chat-area messages-container">
          {messages.map((msg, index) => (
            <ChatMessage
              key={msg.id ?? `${currentSessionId}-${index}`}
              message={msg}
            />
          ))}
          {isLoading && <TypingIndicator />}
          <div ref={bottomRef} />
        </div>

        <ChatInput onSend={sendMessage} disabled={isLoading} />
      </div>
    </div>
  );
}
