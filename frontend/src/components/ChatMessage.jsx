import ExerciseCard from "./ExerciseCard";

export default function ChatMessage({ message, onExerciseClick }) {
  const isCoach = message.role === "coach";

  return (
    <div className={`message ${message.role}`}>
      <span className="message-label">{isCoach ? "Coach" : "You"}</span>

      <div className="message-bubble">{message.content}</div>

      {isCoach && message.safetyNote && (
        <div className="safety-note">
          <span className="safety-note-icon">⚠</span>
          <span>{message.safetyNote}</span>
        </div>
      )}

      {isCoach && message.exercises && message.exercises.length > 0 && (
        <div className="exercise-chips">
          {message.exercises.map((ex) => (
            <ExerciseCard
              key={ex.id}
              exercise={ex}
              onClick={() => onExerciseClick(ex.id)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
