import { useCallback, useEffect, useMemo, useState } from 'react';
import { apiRequest, apiUrl, getApiErrorMessage, ApiError } from './api/client';
import { AuthContext } from './auth/context';

export function AuthProvider({ children }) {
  const [token, setToken] = useState(() => localStorage.getItem('bn_token'));
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [authError, setAuthError] = useState(null);
  const [authReady, setAuthReady] = useState(false);
  const [retryCount, setRetryCount] = useState(0);

  useEffect(() => {
    const expireSession = () => {
      localStorage.removeItem('bn_token');
      setToken(null);
      setUser(null);
      setAuthError('Sua sessão expirou. Entre novamente com o Discord.');
    };
    window.addEventListener('bn:session-expired', expireSession);
    return () => window.removeEventListener('bn:session-expired', expireSession);
  }, []);

  useEffect(() => {
    let cancelled = false;
    Promise.resolve().then(() => {
      if (cancelled) return;
      const queryParams = new URLSearchParams(window.location.search);
      const hashParams = new URLSearchParams(window.location.hash.slice(1));
      const urlToken = hashParams.get('token') || queryParams.get('token');
      if (urlToken) {
        localStorage.setItem('bn_token', urlToken);
        setToken(urlToken);
        window.history.replaceState({}, document.title, window.location.pathname);
      }
      setAuthReady(true);
    });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!authReady) return undefined;
    const controller = new AbortController();

    const authenticate = async () => {
      if (!token) {
        setUser(null);
        setAuthError(null);
        setLoading(false);
        return;
      }
      setLoading(true);
      setAuthError(null);
      try {
        const data = await apiRequest('/auth/me', { token, signal: controller.signal });
        if (!controller.signal.aborted) setUser(data);
      } catch (error) {
        if (controller.signal.aborted) return;
        if (error instanceof ApiError && error.status === 401) {
          localStorage.removeItem('bn_token');
          setToken(null);
          setUser(null);
          setAuthError('Sua sessão expirou. Entre novamente com o Discord.');
        } else {
          setUser(null);
          setAuthError(getApiErrorMessage(error));
        }
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    };

    authenticate();
    return () => controller.abort();
  }, [authReady, token, retryCount]);

  const login = useCallback(() => {
    window.location.assign(apiUrl('/auth/login'));
  }, []);

  const logout = useCallback(async () => {
    const activeToken = token;
    localStorage.removeItem('bn_token');
    setToken(null);
    setUser(null);
    setAuthError(null);
    if (activeToken) {
      await apiRequest('/auth/logout', { method: 'POST', token: activeToken }).catch(() => undefined);
    }
  }, [token]);

  const retryAuthentication = useCallback(() => setRetryCount((current) => current + 1), []);
  const value = useMemo(() => ({
    user,
    token,
    isAuthenticated: Boolean(user),
    loading,
    authError,
    login,
    logout,
    retryAuthentication,
  }), [user, token, loading, authError, login, logout, retryAuthentication]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
