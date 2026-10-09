import React from 'react';
import { useAuth } from '../../AuthContext';
import { Shield, Sparkles, MessageSquare, AlertTriangle, Key, Users } from 'lucide-react';

export default function OverviewTab({ setCurrentTab }) {
  const { user } = useAuth();

  const cards = [
    {
      title: "Auto Moderation",
      desc: "Configure regras contra spam, convites de outros servidores e limite de menções.",
      action: "Configurar AutoMod",
      tab: "automod",
      icon: Shield
    },
    {
      title: "Casos de Moderação",
      desc: "Visualize advertências, banimentos e histórico punitivo dos membros.",
      action: "Ver casos",
      tab: "moderation",
      icon: AlertTriangle
    },
    {
      title: "Configurações Gerais",
      desc: "Ajuste o idioma, fuso horário e recursos ativos do bot.",
      action: "Abrir configurações",
      tab: "settings",
      icon: Key
    },
    {
      title: "Economia do Servidor",
      desc: "Gerencie itens da loja, saldos em carteira e salários de cargos.",
      action: "Gerenciar economia",
      tab: "economy",
      icon: Sparkles
    }
  ];

  return (
    <div>
      <div className="mb-8">
        <h1 className="text-3xl font-extrabold text-white">
          Bem-vindo, <span className="text-bn-blue">{user?.username}</span>
        </h1>
        <p className="text-sm text-bn-muted mt-1">Abaixo estão os módulos rápidos mais utilizados no servidor.</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
        {cards.map((c, i) => {
          const Icon = c.icon;
          return (
            <div key={i} className="p-6 rounded-2xl bg-bn-card border border-bn-border flex flex-col justify-between hover:border-bn-border/80 transition-all">
              <div>
                <div className="w-10 h-10 rounded-xl bg-bn-dark/80 text-bn-blue flex items-center justify-center mb-4">
                  <Icon className="w-5 h-5" />
                </div>
                <h3 className="text-lg font-bold text-white mb-1.5">{c.title}</h3>
                <p className="text-xs text-bn-muted leading-relaxed mb-6">{c.desc}</p>
              </div>

              <button 
                onClick={() => setCurrentTab(c.tab)}
                className="px-4 py-2 rounded-xl bg-bn-dark hover:bg-bn-border text-white text-xs font-semibold self-start transition-all cursor-pointer"
              >
                {c.action}
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}