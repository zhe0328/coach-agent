// components/Login.jsx
import { useState } from "react";
import "./UserAuth.css";
import { exerciseApi } from "../api/exercise";

export default function Login({ onAuthSuccess, onToggleMode }) {
    const [username, setUsername] = useState("");
    const [password, setPassword] = useState("");
    const [error, setError] = useState("");

    const handleSubmit = async (e) => {
        e.preventDefault();
        setError("");
        const payload = {
            username: username,
            password: password
        }
        await exerciseApi.login(payload)
            .then((data) => {
                console.log(data)
                if (data.status === "success") {
                    localStorage.setItem("current_user_id", data.user_id);
                    localStorage.setItem("current_username", data.username);
                    onAuthSuccess(data.user_id, data.username);
                }
            })
            .catch((err) => {
                setError(err.message);
            });
    };

    return (
        <div className="auth-card login-mini">
            <div className="auth-header">
                <h2>Coach Agent</h2>
                <p>重新唤醒您的历史训练打卡数据与生理学记忆防线</p>
            </div>

            {error && <div className="auth-error-badge">⚠️ {error}</div>}

            <form onSubmit={handleSubmit} className="auth-form">
                <div className="form-group">
                    <label>账户昵称</label>
                    <input type="text" required placeholder="请输入您的注册名" value={username} onChange={e => setUsername(e.target.value)} />
                </div>
                <div className="form-group">
                    <label>安全密码</label>
                    <input type="password" required placeholder="请输入密码" value={password} onChange={e => setPassword(e.target.value)} />
                </div>
                <button type="submit" className="auth-submit-btn">拉取分布式记忆并开启对话</button>
                <p className="auth-toggle-link">
                    还没有账户？ <span onClick={onToggleMode}>立即建立指纹问卷 ➔</span>
                </p>
            </form>
        </div>
    );
}
