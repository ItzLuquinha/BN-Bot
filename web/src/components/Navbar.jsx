import React from 'react';
import { useAuth } from '../AuthContext';
import { LogOut, User } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

export default function Navbar({ guildName }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  return (
    <header className="h-16 border-b border-bn-border bg-bn-dark/80 backdrop-blur-md sticky top-0 z-40 px-6 flex items-center justify-between">
      <div className="flex items-center gap-3">
        <div 
          onClick={() => navigate('/')} 
          className="flex items-center gap-2 cursor-pointer"
        >
          <div className="w-8 h-8 rounded-lg bg-bn-card flex items-center justify-center border border-bn-border">
            <span className="font-extrabold text-sm text-white">B</span>
            <span className="font-extrabold text-sm text-bn-green">N</span>
          </div>
          <span className="font-bold text-white text-base">BN <span className="text-bn-green">Bot</span></span>
        </div>

        {guildName && (
          <>
            <span className="text-bn-border">/</span>
            <span className="text-sm font-semibold text-bn-muted">{guildName}</span>
          </>
        )}
      </div>

      <div className="flex items-center gap-3">
        <div className="flex items-center gap-2.5 bg-bn-card border border-bn-border px-3 py-1.5 rounded-xl">
          {user?.avatar ? (
            <img 
              src={`https://cdn.discordapp.com/avatars/${user.id}/${user.avatar}.png`} 
              alt="" 
              className="w-6 h-6 rounded-full border border-bn-green"
            />
          ) : (
            <User className="w-5 h-5 text-bn-muted" />
          )}
          <span className="text-xs font-bold text-white">{user?.username}</span>
          <span className="text-[10px] uppercase font-bold text-bn-green px-1.5 py-0.5 rounded bg-bn-green/10">
            {user?.system_role}
          </span>
        </div>

        <button 
          onClick={logout} 
          title="Sair"
          className="p-2 rounded-xl bg-bn-card border border-bn-border hover:border-red-500/50 hover:text-red-400 text-bn-muted transition-colors cursor-pointer"
        >
          <LogOut className="w-4 h-4" />
        </button>
      </div>
    </header>
  );
}