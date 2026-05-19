import React from "react";
import "./NewSessionButton.css"; 

export default function NewSessionButton({ onSessionReset }) {
  const handleReset = () => {
    if (window.confirm("确定要开启新的训练吗？这将清空当前的多轮对话背景与自愈状态。")) {
      // 1. 物理清空前端固化的会话 ID
      localStorage.removeItem("current_fitness_session_id");
      
      // 2. 强制生成一个全新的 UUID（让后端的自愈计数和 Redis 队列瞬间归零）
      const newSessionId = crypto.randomUUID();
      localStorage.setItem("current_fitness_session_id", newSessionId);
      
      // 3. 回调给父组件 App.jsx 清空界面消息记录
      onSessionReset(newSessionId);
      console.log(`🧠 [Memory] 已强切全新会话工作记忆空间，ID: ${newSessionId}`);
    }
  };

  return (
    <button className="new-session-btn" onClick={handleReset}>
      <span className="btn-icon">↺</span>
      新对话 / 清除记忆
    </button>
  );
}
