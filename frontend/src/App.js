import { useState, useRef, useEffect } from "react";
import ChatMessage from "./components/ChatMessage";
import ChatInput from "./components/ChatInput";
import { exerciseApi } from "./api/exercise";
import "./App.css";

const WELCOME = {
  id: "welcome",
  role: "coach",
  // 模拟一个简单的结构化对象，保持组件渲染一致性
  content: {
    greeting: "你好！我是你的专属 AI 健身教练。",
    detailed_guidance: "告诉我的你的健身目标、可用器材、体能水平或任何伤病情况 —— 我将为你量身定制训练计划。",
    response_type: "knowledge"
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

  const sendMessage = async (text) => {
    if (!text.trim()) return;

    // 1. 添加用户消息
    const userMsg = { id: Date.now(), role: "user", content: text };
    setMessages((prev) => [...prev, userMsg]);
    
    setIsLoading(true);
    const user_id = 123; // 实际项目中应来自 Auth 上下文

    try {
      // 2. 调用后端 Orchestrator 接口
      const responseStr = await exerciseApi.getAiRecommendation(user_id, text);
      
      // 关键步骤：解析字符串为 JSON 对象
      let data;
      try {
        data = typeof responseStr === 'string' ? JSON.parse(responseStr) : responseStr;
      } catch (e) {
        console.error("JSON 解析失败:", e);
        throw new Error("数据格式错误");
      }
      
      // 3. 构造教练消息对象 (存储完整的结构化 CoachResponse)
      const coachMsg = {
        id: Date.now() + 1,
        role: "coach",
        content: data, // 这是一个包含 response_type, exercises, safety_alerts 等的对象
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
            greeting: "出错了...",
            detailed_guidance: "抱歉，服务器连接失败。请检查后端是否正常运行后重试。",
            response_type: "knowledge"
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
        </div>
      </header>

      <main className="chat-area">
        <div className="messages-container">
          {messages.map((msg) => (
            <ChatMessage
              key={msg.id}
              message={msg}
              // 注意：此时不再需要传递 onExerciseClick，因为渲染逻辑已下沉到 Recommendation 内部
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
