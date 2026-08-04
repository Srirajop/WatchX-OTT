import React, { useState, useEffect } from 'react';
import axios from 'axios';

const API = '/api/auth';

const st = {
  container: { display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '100vh', background: '#f8fafc', padding: 20 },
  card: { background: '#fff', padding: '40px', borderRadius: 12, boxShadow: '0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06)', width: '100%', maxWidth: 400 },
  title: { fontSize: 24, fontWeight: 800, color: '#0f172a', marginBottom: 24, textAlign: 'center' },
  input: { width: '100%', padding: '12px 16px', borderRadius: 8, border: '1px solid #cbd5e1', fontSize: 14, marginBottom: 16, boxSizing: 'border-box' },
  btn: { width: '100%', padding: '12px', background: '#0f766e', color: '#fff', border: 'none', borderRadius: 8, fontSize: 15, fontWeight: 700, cursor: 'pointer', marginBottom: 16 },
  link: { color: '#0f766e', fontSize: 13, cursor: 'pointer', textDecoration: 'underline', textAlign: 'center', display: 'block', background: 'none', border: 'none', width: '100%' },
  error: { background: '#fee2e2', color: '#991b1b', padding: 12, borderRadius: 8, fontSize: 13, marginBottom: 16 },
  success: { background: '#dcfce3', color: '#166534', padding: 12, borderRadius: 8, fontSize: 13, marginBottom: 16 }
};

export default function Auth({ onLogin }) {
  const [view, setView] = useState('login'); // login, signup, forgot, reset, verify
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [loading, setLoading] = useState(false);
  const [resetToken, setResetToken] = useState('');

  // Password Rules
  const reqs = [
    { label: 'Min 8 characters', met: password.length >= 8 },
    { label: 'Uppercase letter', met: /[A-Z]/.test(password) },
    { label: 'Lowercase letter', met: /[a-z]/.test(password) },
    { label: 'Special character', met: /[!@#$%^&*(),.?":{}|<>]/.test(password) }
  ];
  const allReqsMet = reqs.every(r => r.met);
  const passwordsMatch = password && confirmPassword && password === confirmPassword;

  // Check URL for tokens on mount
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const rToken = params.get('reset_token');
    const vToken = params.get('verify_token');
    
    if (rToken) {
      setResetToken(rToken);
      setView('reset');
    } else if (vToken) {
      setView('verify');
      verifyEmail(vToken);
    }
  }, []);

  const clearMsgs = () => { setError(''); setSuccess(''); };

  const verifyEmail = async (token) => {
    setLoading(true);
    try {
      const res = await axios.post(`${API}/verify-email`, { token });
      setSuccess(res.data.message);
      setTimeout(() => {
        window.history.replaceState({}, document.title, "/");
        setView('login');
      }, 3000);
    } catch (err) {
      setError(err.response?.data?.detail || 'Verification failed. Link may be expired.');
    } finally { setLoading(false); }
  };

  const handleLogin = async (e) => {
    e.preventDefault();
    clearMsgs(); setLoading(true);
    try {
      const res = await axios.post(`${API}/login`, { email, password });
      onLogin(res.data.access_token);
    } catch (err) {
      setError(err.response?.data?.detail || 'Login failed.');
    } finally { setLoading(false); }
  };

  const handleSignup = async (e) => {
    e.preventDefault();
    clearMsgs();
    if (!email.endsWith('@ewandzdigital.com')) {
      setError('Only @ewandzdigital.com emails are allowed.');
      return;
    }
    if (!allReqsMet || !passwordsMatch) {
      setError('Please ensure all password requirements are met and passwords match.');
      return;
    }
    
    setLoading(true);
    try {
      const res = await axios.post(`${API}/signup`, { email, password });
      setSuccess(res.data.message || 'Account created! Please check your email to verify.');
      setView('login');
      setPassword('');
      setConfirmPassword('');
    } catch (err) {
      setError(err.response?.data?.detail || 'Sign up failed.');
    } finally { setLoading(false); }
  };

  const handleForgot = async (e) => {
    e.preventDefault();
    clearMsgs(); setLoading(true);
    try {
      const res = await axios.post(`${API}/forgot-password`, { email });
      setSuccess(res.data.message);
    } catch (err) {
      setError(err.response?.data?.detail || 'Request failed.');
    } finally { setLoading(false); }
  };

  const handleReset = async (e) => {
    e.preventDefault();
    clearMsgs(); setLoading(true);
    try {
      const res = await axios.post(`${API}/reset-password`, { token: resetToken, new_password: password });
      setSuccess(res.data.message);
      setTimeout(() => {
        window.history.replaceState({}, document.title, "/");
        setView('login');
        setPassword('');
      }, 2000);
    } catch (err) {
      setError(err.response?.data?.detail || 'Reset failed.');
    } finally { setLoading(false); }
  };

  return (
    <div style={st.container}>
      <div style={st.card}>
        <h2 style={st.title}>
          {view === 'login' ? 'Welcome Back' : view === 'signup' ? 'Create Account' : view === 'forgot' ? 'Reset Password' : view === 'verify' ? 'Verifying Email' : 'New Password'}
        </h2>

        {error && <div style={st.error}>{error}</div>}
        {success && <div style={st.success}>{success}</div>}

        {view === 'verify' && loading && (
          <div style={{ textAlign: 'center', color: '#64748b' }}>Verifying your email address, please wait...</div>
        )}

        {view === 'verify' && !loading && (
          <button type="button" style={{ ...st.btn, marginTop: 16 }} onClick={() => { window.history.replaceState({}, document.title, "/"); setView('login'); clearMsgs(); }}>Go to Log In</button>
        )}

        {view === 'login' && (
          <form onSubmit={handleLogin}>
            <input style={st.input} type="email" placeholder="Email" value={email} onChange={e => setEmail(e.target.value)} required />
            <input style={st.input} type="password" placeholder="Password" value={password} onChange={e => setPassword(e.target.value)} required />
            <button style={{ ...st.btn, opacity: loading ? 0.7 : 1 }} disabled={loading}>{loading ? 'Logging in...' : 'Log In'}</button>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 10 }}>
              <button type="button" style={{...st.link, width: 'auto'}} onClick={() => { setView('forgot'); clearMsgs(); }}>Forgot Password?</button>
              <button type="button" style={{...st.link, width: 'auto'}} onClick={() => { setView('signup'); clearMsgs(); }}>Create Account</button>
            </div>
          </form>
        )}

        {view === 'signup' && (
          <form onSubmit={handleSignup}>
            <input style={st.input} type="email" placeholder="Email (@ewandzdigital.com)" value={email} onChange={e => setEmail(e.target.value)} required />
            <input style={st.input} type="password" placeholder="Password" value={password} onChange={e => setPassword(e.target.value)} required />
            
            <div style={{ marginBottom: 16, fontSize: 13, background: '#f8fafc', padding: 12, borderRadius: 8, border: '1px solid #e2e8f0' }}>
              <div style={{ fontWeight: 600, marginBottom: 8, color: '#334155' }}>Password Requirements:</div>
              {reqs.map((r, idx) => (
                <div key={idx} style={{ color: r.met ? '#16a34a' : '#94a3b8', display: 'flex', alignItems: 'center', marginBottom: 4 }}>
                  {r.met ? '✅' : '❌'} <span style={{ marginLeft: 8, textDecoration: r.met ? 'line-through' : 'none' }}>{r.label}</span>
                </div>
              ))}
            </div>

            <input style={st.input} type="password" placeholder="Confirm Password" value={confirmPassword} onChange={e => setConfirmPassword(e.target.value)} required />
            
            {password && confirmPassword && (
              <div style={{ fontSize: 13, marginBottom: 16, color: passwordsMatch ? '#16a34a' : '#dc2626' }}>
                {passwordsMatch ? '✅ Passwords match' : '❌ Passwords do not match'}
              </div>
            )}

            <button style={{ ...st.btn, opacity: (loading || !allReqsMet || !passwordsMatch) ? 0.7 : 1 }} disabled={loading || !allReqsMet || !passwordsMatch}>
              {loading ? 'Signing up...' : 'Sign Up'}
            </button>
            <button type="button" style={st.link} onClick={() => { setView('login'); clearMsgs(); }}>Back to Log In</button>
          </form>
        )}

        {view === 'forgot' && (
          <form onSubmit={handleForgot}>
            <p style={{ fontSize: 13, color: '#475569', marginBottom: 16, textAlign: 'center' }}>Enter your email address and we'll send you a link to reset your password.</p>
            <input style={st.input} type="email" placeholder="Email" value={email} onChange={e => setEmail(e.target.value)} required />
            <button style={{ ...st.btn, opacity: loading ? 0.7 : 1 }} disabled={loading}>{loading ? 'Sending...' : 'Send Reset Link'}</button>
            <button type="button" style={st.link} onClick={() => { setView('login'); clearMsgs(); }}>Back to Log In</button>
          </form>
        )}

        {view === 'reset' && (
          <form onSubmit={handleReset}>
            <input style={st.input} type="password" placeholder="New Password" value={password} onChange={e => setPassword(e.target.value)} required />
            <button style={{ ...st.btn, opacity: loading ? 0.7 : 1 }} disabled={loading}>{loading ? 'Resetting...' : 'Reset Password'}</button>
          </form>
        )}
      </div>
    </div>
  );
}
