import React from 'react';
import { 
  Home, Settings, ShieldAlert, Shield, 
  Coins, FileText, ChevronLeft, Bell, Users
} from 'lucide-react';
import { useNavigate } from 'react-router-dom';

export default function Sidebar({ currentTab, setCurrentTab, guild }) {
  const navigate = useNavigate();

  const menuSections = [
    {
      title: "PRINCIPAL",
      items: [
        { id: "overview", label: "Início / Overview", icon: Home },
        { id: "settings", label: "Configurações Gerais", icon: Settings },
      ]
    },
    {
      title: "SEGURANÇA & MOD",
      items: [
        { id: "automod", label: "Auto Moderation", icon: ShieldAlert },
        { id: "moderation", label: "Casos de Moderação", icon: Shield },
      ]
    },
    {
      title: "MÓDULOS",
      items: [
        { id: "economy", label: "Economia & Loja", icon: Coins },
        { id: "members", label: "Membros & Níveis", icon: Users },
        { id: "logs", label: "Logs de Auditoria", icon: FileText },
      ]
    }
  ];

  return (
    <aside className="w-64 bg-bn-card border-r border-bn-border flex flex-col h-screen sticky top-0">
      {/* Botão de Voltar para os Servidores */}
      <div className="p-4 border-b border-bn-border">
        <button 
          onClick={() => navigate('/servers')}
          className="flex items-center gap-2 text-xs font-semibold text-bn-muted hover:text-white transition-colors cursor-pointer"
        >
          <ChevronLeft className="w-4 h-4" />
          <span>Trocar de Servidor</span>
        </button>

        {/* Servidor Ativo */}
        <div className="mt-3 flex items-center gap-3 p-2 rounded-xl bg-bn-dark/60 border border-bn-border">
          {guild?.icon_url ? (
            <img src={guild.icon_url} alt="" className="w-8 h-8 rounded-lg" />
          ) : (
            <div className="w-8 h-8 rounded-lg bg-bn-border flex items-center justify-center font-bold text-white text-xs">
              {guild?.name?.[0] || 'S'}
            </div>
          )}
          <span className="font-bold text-sm text-white truncate">{guild?.name || 'Carregando...'}</span>
        </div>
      </div>

      {/* Menus */}
      <div className="flex-1 overflow-y-auto p-4 space-y-6">
        {menuSections.map((section, idx) => (
          <div key={idx}>
            <p className="text-[10px] font-bold tracking-wider text-bn-muted/70 uppercase mb-2 px-2">
              {section.title}
            </p>
            <div className="space-y-1">
              {section.items.map((item) => {
                const Icon = item.icon;
                const active = currentTab === item.id;
                return (
                  <button
                    key={item.id}
                    onClick={() => setCurrentTab(item.id)}
                    className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-xl font-medium text-sm transition-all cursor-pointer ${
                      active 
                        ? 'bg-bn-green/15 text-bn-green border border-bn-green/30 shadow-glow-green/20' 
                        : 'text-bn-muted hover:text-white hover:bg-bn-border/40'
                    }`}
                  >
                    <Icon className="w-4 h-4" />
                    <span>{item.label}</span>
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </aside>
  );
}