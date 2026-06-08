import Recommendation from "./Recommendation";

export default function ChatMessage({ message }) {
  const isCoach = message.role === "coach";
  console.log("current message: ", message);

  return (
    <div className={`message ${message.role}`}>
      {/* 角色标签 */}
      <span className="message-label">
        {isCoach ? "Coach" : "You"}
      </span>

      {/* 内容渲染区域 */}
      <div className="message-content">
        {isCoach ? (
          // AI 消息：如果 content 是对象，则调用结构化组件；否则兜底渲染 text
          typeof message.content === "object" && message.content !== null ? (
            <div className="message-bubble">
              <Recommendation data={message.content} />
            </div>
          ) : (
            <div className="message-bubble">{message.text || message.content}</div>
          )
        ) : (
          // 用户消息：直接显示文本气泡
          <div className="message-bubble">{message.content}</div>
        )}
      </div>
    </div>
  );
}
