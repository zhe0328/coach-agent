import { useState, useRef, useEffect } from "react";
import ChatMessage from "./components/ChatMessage";
import ChatInput from "./components/ChatInput";
import ExerciseModal from "./components/ExerciseModal";
import { exerciseApi } from "./api/exercise";
import "./App.css";

const WELCOME = {
  id: "welcome",
  role: "coach",
  content:
    "Hi! I'm your personal fitness coach.\n\nTell me about your goals, available equipment, fitness level, or any injuries — I'll put together a workout plan tailored to you.",
  exercises: [],
};

export default function App() {
  const [messages, setMessages] = useState([WELCOME]);
  const [isLoading, setIsLoading] = useState(false);
  const [selectedExerciseId, setSelectedExerciseId] = useState(null);
  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isLoading]);

  const sendMessage = async (text) => {
    const userMsg = { id: Date.now(), role: "user", content: text };
    setMessages((prev) => [...prev, userMsg]);
    setIsLoading(true);

    try {
      const data = await exerciseApi.getAiRecommendation(text);
      const coachMsg = {
        id: Date.now() + 1,
        role: "coach",
        content: data.warmup_tips || "Here's a plan based on your request:",
        safetyNote: data.safety_notes || null,
        exercises: data.planned_exercises ?? [],
      };
      setMessages((prev) => [...prev, coachMsg]);
    } catch {
      setMessages((prev) => [
        ...prev,
        {
          id: Date.now() + 1,
          role: "coach",
          content:
            "Sorry, I couldn't reach the server. Please make sure the backend is running and try again.",
          exercises: [],
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
          <span className="header-tag">AI Fitness Coach</span>
        </div>
      </header>

      <main className="chat-area">
        <div className="messages-container">
          {messages.map((msg) => (
            <ChatMessage
              key={msg.id}
              message={msg}
              onExerciseClick={setSelectedExerciseId}
            />
          ))}
          {isLoading && <TypingIndicator />}
          <div ref={bottomRef} />
        </div>
      </main>

      <ChatInput onSend={sendMessage} disabled={isLoading} />

      {selectedExerciseId && (
        <ExerciseModal
          exerciseId={selectedExerciseId}
          onClose={() => setSelectedExerciseId(null)}
        />
      )}
    </div>
  );
}

function TypingIndicator() {
  return (
    <div className="message coach">
      <span className="message-label">Coach</span>
      <div className="typing-indicator">
        <span />
        <span />
        <span />
      </div>
    </div>
  );
}
