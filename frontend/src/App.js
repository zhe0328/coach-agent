import { useEffect, useState } from "react";
import Login from "./components/Login";
import Signup from "./components/Signup";
import Profile from "./components/Profile";
import ChatDashboard from "./components/ChatDashboard";
import { clearAuthSession, setUnauthorizedHandler } from "./api/authSession";
import "./App.css";

export default function App() {
  const [userId, setUserId] = useState(() =>
    localStorage.getItem("current_user_id"),
  );
  const [username, setUsername] = useState(() =>
    localStorage.getItem("current_username"),
  );
  const [authMode, setAuthMode] = useState("login");
  const [showProfile, setShowProfile] = useState(false);

  useEffect(() => {
    setUnauthorizedHandler(() => {
      setUserId(null);
      setUsername(null);
      setAuthMode("login");
      setShowProfile(false);
    });

    const storedUserId = localStorage.getItem("current_user_id");
    const token = localStorage.getItem("access_token");
    if (storedUserId && !token) {
      clearAuthSession();
      setUserId(null);
      setUsername(null);
    }
  }, []);

  const handleAuthSuccess = (id, name) => {
    localStorage.removeItem("current_fitness_session_id");
    setUserId(String(id));
    setUsername(name);
    localStorage.setItem("current_user_id", String(id));
    localStorage.setItem("current_username", name);
  };

  const handleLogout = () => {
    clearAuthSession();
    setUserId(null);
    setUsername(null);
    setAuthMode("login");
    setShowProfile(false);
  };

  return (
    <div className={`app-layout${userId ? " app-layout--chat" : ""}`}>
      <header className="app-header">
        <div className="header-inner">
          <div className="logo">
            <span className="logo-icon">◈</span>
            <span className="logo-text">CoachAgent</span>
          </div>
          <span className="header-tag">专业级 AI 教练</span>

          {userId && (
            <div className="header-controls-group">
              <span
                className="user-welcome-tag"
                onClick={() => setShowProfile(true)}
              >
                🏋️‍♂️ 会员: <strong>{username}</strong>
              </span>
              <button className="logout-action-btn" onClick={handleLogout}>
                退出
              </button>
            </div>
          )}
        </div>
      </header>

      {!userId ? (
        <main className="auth-container-gate">
          {authMode === "login" ? (
            <Login
              onAuthSuccess={handleAuthSuccess}
              onToggleMode={() => setAuthMode("signup")}
            />
          ) : (
            <Signup onAuthSuccess={handleAuthSuccess} />
          )}
        </main>
      ) : (
        <ChatDashboard userId={userId} />
      )}

      {showProfile && (
        <Profile userId={userId} onClose={() => setShowProfile(false)} />
      )}
    </div>
  );
}
