import Recommendation from "./Recommendation";

export default function ChatMessage({ message }) {
  const isCoach = message.role === "coach";

  return (
    <div className={`message ${message.role}`}>
      <span className="message-label">
        {isCoach ? "Coach" : "You"}
      </span>

      <div className="message-content">
        {isCoach ? (
          typeof message.content === "object" && message.content !== null ? (
            <div className="message-bubble">
              <Recommendation
                data={message.content}
                streaming={Boolean(message.streaming)}
                enriching={Boolean(message.enriching)}
                pipelineStatus={message.pipelineStatus}
              />
            </div>
          ) : (
            <div className="message-bubble">{message.text || message.content}</div>
          )
        ) : (
          <div className="message-bubble">{message.content}</div>
        )}
      </div>
    </div>
  );
}
