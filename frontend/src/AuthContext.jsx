import { createContext, useContext, useState, useEffect } from "react";
import { login as apiLogin, signup as apiSignup, getMe } from "./api.js";

const TOKEN_STORAGE_KEY = "gradeops_token";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [token, setToken] = useState(() =>
    localStorage.getItem(TOKEN_STORAGE_KEY),
  );
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(() =>
    Boolean(localStorage.getItem(TOKEN_STORAGE_KEY)),
  );

  // On mount (or when the token changes), verify it's still valid and load
  // the user's info -- this is what keeps someone logged in across a page
  // refresh, rather than forcing a fresh login every time.
  useEffect(() => {
    if (!token) {
      return;
    }
    getMe(token)
      .then(setUser)
      .catch(() => {
        // Token expired or invalid -- clear it and fall back to logged-out state
        localStorage.removeItem(TOKEN_STORAGE_KEY);
        setToken(null);
        setUser(null);
      })
      .finally(() => setLoading(false));
  }, [token]);

  async function login(email, password) {
    const data = await apiLogin(email, password);
    localStorage.setItem(TOKEN_STORAGE_KEY, data.access_token);
    setToken(data.access_token);
    setUser(data.user);
  }

  async function signup(email, password, name) {
    const data = await apiSignup(email, password, name);
    localStorage.setItem(TOKEN_STORAGE_KEY, data.access_token);
    setToken(data.access_token);
    setUser(data.user);
  }

  function logout() {
    localStorage.removeItem(TOKEN_STORAGE_KEY);
    setToken(null);
    setUser(null);
  }

  return (
    <AuthContext.Provider
      value={{ token, user, loading, login, signup, logout }}
    >
      {children}
    </AuthContext.Provider>
  );
}

// This hook is intentionally colocated with its context provider so consumers
// can import both from the same module.
// eslint-disable-next-line react-refresh/only-export-components
export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
}
