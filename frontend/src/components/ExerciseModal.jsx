import { useEffect, useState, useCallback } from "react";
import { exerciseApi } from "../api/exercise";

export default function ExerciseModal({ exerciseId, onClose }) {
  const [exercise, setExercise] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    exerciseApi
      .getExerciseDetail(exerciseId)
      .then((data) => {
        if (!cancelled) {
          setExercise(data);
          setLoading(false);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setError("Could not load exercise details.");
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [exerciseId]);

  const handleBackdropClick = useCallback(
    (e) => {
      if (e.target === e.currentTarget) onClose();
    },
    [onClose],
  );

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const difficulty = exercise?.difficulty?.toLowerCase() ?? "";

  return (
    <div className="modal-backdrop" onClick={handleBackdropClick}>
      <div className="modal-panel" role="dialog" aria-modal="true">
        <div className="modal-header">
          <h2 className="modal-title">
            {loading ? "Loading…" : (exercise?.name_zh ?? "Exercise")}
          </h2>
          <button className="modal-close" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>

        <div className="modal-body">
          {loading && (
            <div className="modal-loading">
              <div className="modal-loading-dots">
                <span />
                <span />
                <span />
              </div>
              Fetching details…
            </div>
          )}

          {error && <div className="modal-error">{error}</div>}

          {exercise && !loading && (
            <>
              <div className="modal-meta">
                <span className={`meta-tag difficulty ${difficulty}`}>
                  {difficulty}
                </span>
                <span className="meta-tag">🎯 {exercise.target_zh}</span>
                <span className="meta-tag">🛠 {exercise.equipment_zh}</span>
                <span className="meta-tag">📍 {exercise.body_part_zh}</span>
              </div>

              {exercise.description_zh && (
                <div>
                  <p className="modal-section-title">About</p>
                  <p className="modal-description">{exercise.description_zh}</p>
                </div>
              )}

              {exercise.instructions_zh?.length > 0 && (
                <div>
                  <p className="modal-section-title">
                    Step-by-step instructions
                  </p>
                  <ol className="instructions-list">
                    {exercise.instructions_zh.map((step, i) => (
                      <li key={i} className="instruction-step">
                        <span className="step-number">{i + 1}</span>
                        <span className="step-text">{step}</span>
                      </li>
                    ))}
                  </ol>
                </div>
              )}

              {exercise.secondary_muscles_zh?.length > 0 && (
                <div>
                  <p className="modal-section-title">Secondary muscles</p>
                  <div className="muscles-list">
                    {exercise.secondary_muscles_zh.map((m) => (
                      <span key={m} className="muscle-tag">
                        {m}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
