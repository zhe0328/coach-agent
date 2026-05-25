import { useState, useRef, useEffect } from "react";
import ChatMessage from "./components/ChatMessage";
import ChatInput from "./components/ChatInput";
import NewSessionButton from "./components/NewSessionButton";
import Login from "./components/Login";
import Signup from "./components/Signup";
import Profile from "./components/Profile";
import { exerciseApi } from "./api/exercise";
import "./App.css";

const WELCOME = {
  id: "welcome",
  role: "coach",
  content: {
    greeting: "你好！我是你的专业级 AI 健身教练。",
    detailed_guidance: "我已经同步加载了你在 Neo4j 中的长效解剖学受损关节防线。请直接告诉我你今天的训练目标！",
    response_type: "knowledge",
    safety_alerts: [],
    exercises: []
  },
};

export default function App() {
  // ── 1. 💡【鉴权与会话状态机管理中心】 ────────────────────────
  const [userId, setUserId] = useState(() => localStorage.getItem("current_user_id"));
  const [username, setUsername] = useState(() => localStorage.getItem("current_username"));
  const [authMode, setAuthMode] = useState("login"); // login | signup
  const [showProfile, setShowProfile] = useState(false); // 个人中心弹窗控制

  // ── 2. 聊天区域核心状态 ───────────────────────────────────
  const [messages, setMessages] = useState([WELCOME]);
  const [isLoading, setIsLoading] = useState(false);
  const bottomRef = useRef(null);

  // 自动滚动到底部
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isLoading]);

  // 💡【工作记忆重置回调】
  const handleSessionReset = (newSessionId) => {
    setMessages([WELCOME]);
  };

  // 💡【登录/注册鉴权成功回调中心】
  const handleAuthSuccess = (id, name) => {
    setUserId(id);
    setUsername(name);
    setMessages([WELCOME]); // 唤醒专属欢迎语
  };

  // 💡【退出登录/注销钢印】
  const handleLogout = () => {
    localStorage.removeItem("current_user_id");
    localStorage.removeItem("current_username");
    localStorage.removeItem("current_fitness_session_id");
    setUserId(null);
    setUsername(null);
    setAuthMode("login");
  };

  const sendMessage = async (text) => {
    if (!text.trim()) return;

    // 1. 添加用户提问气泡
    const userMsg = { id: Date.now(), role: "user", content: text };
    setMessages((prev) => [...prev, userMsg]);
    
    setIsLoading(true);

    try {
      // 2. 🧠【分布式工作记忆锁】：锁定前端会话唯一 ID
      let sessionId = localStorage.getItem("current_fitness_session_id");
      if (!sessionId) {
          sessionId = crypto.randomUUID();
          localStorage.setItem("current_fitness_session_id", sessionId);
      }

      const responseStr = await exerciseApi.getAiRecommendation(sessionId, userId, text);
      
      // 4. 解析同步返回的完整结构化 JSON 块
      let data;
      try {
        data = typeof responseStr === 'string' ? JSON.parse(responseStr) : responseStr;
      } catch (e) {
        console.error("JSON 解析失败:", e);
        throw new Error("后端返回的 CoachResponse 结构体破损");
      }
      
      // 5. 构造教练消息对象
      const coachMsg = {
        id: Date.now() + 1,
        role: "coach",
        content: data,
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
            detailed_guidance: "服务器管线断裂，原因极可能是后端自愈重试三次后触及最高安全硬性拦截死锁，请检查后台日志。",
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
      {/* ── 3. 统一全局的高端钢蓝 Header 区域 ─────────────────── */}
      <header className="app-header">
        <div className="header-inner">
          <div className="logo">
            <span className="logo-icon">◈</span>
            <span className="logo-text">CoachAgent</span>
          </div>
          <span className="header-tag">专业级 AI 教练</span>
          
          {/* 💡【中枢联动控制】：只有当成功登录后，才渲染右上角的一系列交互操作面板 */}
          {userId && (
            <div className="header-controls-group">
              <span className="user-welcome-tag" onClick={() => setShowProfile(true)}>
                🏋️‍♂️ 会员: <strong>{username}</strong>
              </span>
              <NewSessionButton onSessionReset={handleSessionReset} />
              <button className="logout-action-btn" onClick={handleLogout}>退出</button>
            </div>
          )}
        </div>
      </header>

      {/* ── 4. 网闸条件分流：未登录状态 ── */}
      {!userId ? (
        <main className="auth-container-gate">
          {authMode === "login" ? (
            <Login 
              onAuthSuccess={handleAuthSuccess} 
              onToggleMode={() => setAuthMode("signup")} 
            />
          ) : (
            <Signup 
              onAuthSuccess={handleAuthSuccess} 
            />
          )}
        </main>
      ) : (
        /* ── 5. 网闸条件分流：已登录状态（物理激活主聊天窗口） ── */
        <>
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
        </>
      )}

      {/* ── 6. 个人中心长效语义记忆弹窗 ── */}
      {showProfile && (
        <Profile 
          userId={userId} 
          onClose={() => setShowProfile(false)} 
        />
      )}
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
