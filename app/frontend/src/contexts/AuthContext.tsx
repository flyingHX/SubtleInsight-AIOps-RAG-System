import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from 'react';
import { client } from '../lib/api';

interface User {
  id: string;
  email?: string | null;
  name?: string | null;
}

type AuthStatus = 'loading' | 'authenticated' | 'anonymous';

interface AuthContextType {
  status: AuthStatus;
  user: User | null;
  login: () => void;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | null>(null);

export const useAuth = (): AuthContextType => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};

interface AuthProviderProps {
  children: ReactNode;
}

export const AuthProvider: React.FC<AuthProviderProps> = ({ children }) => {
  const [status, setStatus] = useState<AuthStatus>('loading');
  const [user, setUser] = useState<User | null>(null);

  const refresh = useCallback(async () => {
    setStatus('loading');
    try {
      const res = await client.auth.me();
      if (res?.data) {
        setUser(res.data as User);
        setStatus('authenticated');
      } else {
        setUser(null);
        setStatus('anonymous');
      }
    } catch {
      setUser(null);
      setStatus('anonymous');
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const login = () => {
    client.auth.toLogin();
  };

  const logout = async () => {
    try {
      await client.auth.logout();
    } finally {
      setUser(null);
      setStatus('anonymous');
    }
  };

  const value: AuthContextType = { status, user, login, logout, refresh };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};
