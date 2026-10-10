import { useEffect, useState } from 'react';
import { AlertTriangle, Key, RotateCw, Shield, Sparkles, Users, MessageSquare, Coins, Ticket, Lightbulb } from 'lucide-react';
import { useAuth } from '../../auth/useAuth';
import { apiRequest, getApiErrorMessage } from '../../api/client';

const QUICK_LINKS = [
  { title: 'Auto Moderação', desc: 'Configure regras contra spam, convites e excesso de menções.', action: 'Configurar AutoMod', tab: 'automod', icon: Shield },
  { title: 'Casos de moderação', desc: 'Consulte as ações de moderação registradas no servidor.', action: 'Ver casos', tab: 'moderation', icon: AlertTriangle },
  { title: 'Configurações gerais', desc: 'Ajuste idioma, fuso horário e recursos disponíveis.', action: 'Abrir configurações', tab: 'settings', icon: Key },
  { title: 'Economia do servidor', desc: 'Consulte os saldos que estão persistidos no banco.', action: 'Ver economia', tab: 'economy', icon: Sparkles },
  { title: 'Membros e níveis', desc: 'Consulte membros ativos e seus dados de experiência.', action: 'Ver membros', tab: 'members', icon: Users },
  { title: 'Logs de auditoria', desc: 'Consulte eventos reais de moderação e configuração.', action: 'Ver logs', tab: 'logs', icon: MessageSquare },
];

const METRICS = [
  ['Membros ativos', 'members', Users],
  ['Mensagens registradas', 'messages', MessageSquare],
  ['Avisos ativos', 'warnings', AlertTriangle],
  ['Tickets abertos', 'tickets', Ticket],
  ['Sugestões pendentes', 'pending_suggestions', Lightbulb],
  ['Moedas registradas', 'economy', Coins],
];

export default function OverviewTab({ guildId, token, setCurrentTab }) {
  const { user } = useAuth();
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [retryCount, setRetryCount] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    Promise.resolve()
      .then(() => {
        if (controller.signal.aborted) return null;
        setLoading(true);
        setError(null);
        return apiRequest(`/guilds/${encodeURIComponent(guildId)}/overview`, { token, signal: controller.signal });
      })
      .then((data) => { if (!controller.signal.aborted && data !== null) setSummary(data); })
      .catch((failure) => { if (!controller.signal.aborted) setError(getApiErrorMessage(failure)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [guildId, token, retryCount]);

  const formatMetric = (value) => typeof value === 'number' ? value.toLocaleString('pt-BR', { maximumFractionDigits: 2 }) : '-';

  return (
    <section className="space-y-8">
      <header><h1 className="text-3xl font-extrabold text-white">Bem-vindo, <span className="text-bn-blue">{user?.username || 'moderador'}</span></h1><p className="mt-1 text-sm text-bn-muted">Resumo de dados reais registrados para o servidor selecionado.</p></header>
      {loading && <p role="status" className="rounded-2xl border border-bn-border bg-bn-card p-5 text-sm text-bn-muted">Carregando resumo do servidor…</p>}
      {error && <div className="rounded-2xl border border-red-500/30 bg-bn-card p-5"><p role="alert" className="text-sm text-red-200">{error}</p><button onClick={() => setRetryCount((current) => current + 1)} className="mt-3 inline-flex items-center gap-2 rounded-lg bg-bn-dark px-3 py-2 text-sm text-white"><RotateCw className="h-4 w-4" /> Tentar novamente</button></div>}
      {!loading && !error && summary && <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">{METRICS.map(([label, key, Icon]) => <article key={key} className="rounded-2xl border border-bn-border bg-bn-card p-5"><div className="flex items-center justify-between"><p className="text-sm text-bn-muted">{label}</p><Icon className="h-5 w-5 text-bn-green" /></div><p className="mt-3 text-2xl font-bold text-white">{formatMetric(summary[key])}</p></article>)}</div>}
      <div><h2 className="mb-4 text-xl font-bold text-white">Acesso rápido</h2><div className="grid grid-cols-1 gap-5 md:grid-cols-2">{QUICK_LINKS.map((item) => { const Icon = item.icon; return <article key={item.tab} className="flex flex-col justify-between rounded-2xl border border-bn-border bg-bn-card p-6 transition-all hover:border-bn-border/80"><div><div className="mb-4 flex h-10 w-10 items-center justify-center rounded-xl bg-bn-dark/80 text-bn-blue"><Icon className="h-5 w-5" /></div><h3 className="mb-1.5 text-lg font-bold text-white">{item.title}</h3><p className="mb-6 text-xs leading-relaxed text-bn-muted">{item.desc}</p></div><button onClick={() => setCurrentTab(item.tab)} className="cursor-pointer self-start rounded-xl bg-bn-dark px-4 py-2 text-xs font-semibold text-white transition-all hover:bg-bn-border">{item.action}</button></article>; })}</div></div>
    </section>
  );
}
