export default function ExerciseCard({ exercise, onClick }) {
    const difficulty = exercise.difficulty?.toLowerCase() ?? "";
  
    return (
      <button className="exercise-chip" onClick={() => onClick(exercise)}>
        <span className="chip-name">{exercise.name_zh}</span>
        {difficulty && (
          <span className={`chip-badge ${difficulty}`}>{difficulty}</span>
        )}
        <span className="chip-arrow">›</span>
      </button>
    );
  }
  