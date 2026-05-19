import { useState, useRef, useEffect } from "react";
import ChatMessage from "./components/ChatMessage";
import ChatInput from "./components/ChatInput";
import NewSessionButton from "./components/NewSessionButton";
import { exerciseApi } from "./api/exercise";
import "./App.css";

const WELCOME = {
  id: "welcome",
  role: "coach",
  content: {
    greeting: "你好！我是你的专业级 AI 健身教练。",
    detailed_guidance: "请告诉我你的健身目标、可用器材、体能水平或任何伤病情况 —— 我将为你量身定制训练计划。",
    response_type: "knowledge",
    safety_alerts: [],
    exercises: []
  },
};

export default function App() {
  const [messages, setMessages] = useState([WELCOME]);
  const [isLoading, setIsLoading] = useState(false);
  const bottomRef = useRef(null);

  // 自动滚动到底部
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isLoading]);

  // 💡【工作记忆重置回调】：清空聊天记录，重置为欢迎状态
  const handleSessionReset = (newSessionId) => {
    setMessages([WELCOME]);
  };

  const sendMessage = async (text) => {
    if (!text.trim()) return;

    // 1. 添加用户提问气泡
    const userMsg = { id: Date.now(), role: "user", content: text };
    setMessages((prev) => [...prev, userMsg]);
    
    setIsLoading(true);
    const userId = 123; // 实际项目中从 Auth 上下文读取

    try {
      // 2. 🧠【核心对齐】：锁定或实时初始化前端会话 ID
      let sessionId = localStorage.getItem("current_fitness_session_id");
      if (!sessionId) {
          sessionId = crypto.randomUUID(); // 前端利用原生算法生成唯一全局无状态指纹
          localStorage.setItem("current_fitness_session_id", sessionId);
      }

      // 3. 调用后端 Orchestrator 接口（透传 sessionId）
      // 后端此时会通过这个 ID 读写 Redis 工作记忆，并在 While 循环自愈中流转状态
      const responseStr = await exerciseApi.getAiRecommendation(sessionId, userId, text);
      
      // 4. 解析同步返回的完整结构化 JSON 块
      let data;
      try {
        data = typeof responseStr === 'string' ? JSON.parse(responseStr) : responseStr;
      } catch (e) {
        console.error("JSON 解析失败:", e);
        throw new Error("后端返回的 CoachResponse 结构体破损");
      }
      
      // 5. 构造教练消息对象 (直接存储完全体结构化对象)
      const coachMsg = {
        id: Date.now() + 1,
        role: "coach",
        content: data, // 包含 response_type, exercises, safety_alerts, summary 的纯净数据魔方
      };
      
      setMessages((prev) => [...prev, coachMsg]);
    } catch (error) {
      console.error("Chat Error:", error);
      setMessages((prev) => [
        ...prev,
        {
          id: Date.now() + 1,
          role: "coach",
          content: {
            greeting: "链路发生异常...",
            detailed_guidance: "服务器管线断裂，可能由于后端触发了连续自愈安全红线拦截，或外网大模型连接超时。请检查后台日志。",
            response_type: "knowledge",
            safety_alerts: ["系统级异常防御触发"],
            exercises: []
          }
        },
      ]);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="app-layout">
      <header className="app-header">
        <div className="header-inner">
          <div className="logo">
            <span className="logo-icon">◈</span>
            <span className="logo-text">CoachAgent</span>
          </div>
          <span className="header-tag">专业级 AI 教练</span>
          
          {/* 💡【中枢联动】：把物理刷新按钮挂在 Header 区域，提供干净的系统操控 */}
          <NewSessionButton onSessionReset={handleSessionReset} />
        </div>
      </header>

      <main className="chat-area">
        <div className="messages-container">
          {messages.map((msg) => (
            <ChatMessage
              key={msg.id}
              message={msg}
            />
          ))}
          {isLoading && <TypingIndicator />}
          <div ref={bottomRef} />
        </div>
      </main>

      <ChatInput onSend={sendMessage} disabled={isLoading} />
    </div>
  );
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
