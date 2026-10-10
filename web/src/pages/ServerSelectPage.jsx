import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowRight, RotateCw, Server } from 'lucide-react';
import Navbar from '../components/Navbar';
import { useAuth } from '../auth/useAuth';
import { apiRequest, getApiErrorMessage } from '../api/client';

export default function ServerSelectPage() {
  const { token } = useAuth();
  const [guilds, setGuilds] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [retryCount, setRetryCount] = useState(0);
  const navigate = useNavigate();

  const retry = useCallback(() => setRetryCount((current) => current + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    Promise.resolve()
      .then(() => {
        if (controller.signal.aborted) return null;
        setLoading(true);
        setError(null);
        return apiRequest('/guilds', { token, signal: controller.signal });
      })
      .then((data) => {
        if (!controller.signal.aborted && data !== null) setGuilds(Array.isArray(data) ? data : []);
      })
      .catch((failure) => {
        if (!controller.signal.aborted) setError(getApiErrorMessage(failure));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [token, retryCount]);

  return (
    <div className="flex min-h-screen flex-col bg-bn-dark">
      <Navbar />
      <main className="mx-auto w-full max-w-5xl flex-1 px-6 py-12">
        <h1 className="mb-2 text-3xl font-extrabold text-white">Selecione um servidor</h1>
        <p className="mb-8 text-sm text-bn-muted">Escolha um servidor para o qual sua conta possui permissão de gerenciamento.</p>
        {loading && <p role="status" className="animate-pulse rounded-2xl border border-bn-border bg-bn-card p-8 text-center text-sm text-bn-muted">Carregando servidores…</p>}
        {!loading && error && <div className="rounded-2xl border border-red-500/30 bg-bn-card p-8"><p role="alert" className="text-sm text-red-200">{error}</p><button onClick={retry} className="mt-4 inline-flex items-center gap-2 rounded-xl bg-bn-green px-4 py-2 text-sm font-semibold text-bn-dark"><RotateCw className="h-4 w-4" /> Tentar novamente</button></div>}
        {!loading && !error && guilds?.length === 0 && <div className="rounded-2xl border border-bn-border bg-bn-card p-12 text-center text-sm text-bn-muted">Nenhum servidor ativo disponível para sua conta. Confira se o bot está presente e se você tem permissão para gerenciá-lo.</div>}
        {!loading && !error && guilds?.length > 0 && <div className="grid grid-cols-1 gap-5 md:grid-cols-2 lg:grid-cols-3">{guilds.map((guild) => <button type="button" key={guild.id} onClick={() => navigate(`/dashboard/${encodeURIComponent(guild.id)}`)} className="group flex items-center justify-between rounded-2xl border border-bn-border bg-bn-card p-5 text-left transition-all hover:border-bn-green/50 hover:bg-bn-cardHover"><span className="flex min-w-0 items-center gap-3.5">{guild.icon_url ? <img src={guild.icon_url} alt="" className="h-12 w-12 rounded-xl" /> : <span className="flex h-12 w-12 items-center justify-center rounded-xl bg-bn-border"><Server className="h-6 w-6 text-bn-green" /></span>}<span className="min-w-0"><span className="block truncate text-base font-bold text-white transition-colors group-hover:text-bn-green">{guild.name}</span><span className="block text-[11px] text-bn-muted">ID: {guild.id}</span></span></span><ArrowRight className="h-5 w-5 shrink-0 text-bn-muted transition-all group-hover:translate-x-1 group-hover:text-bn-green" /></button>)}</div>}
      </main>
    </div>
  );
}
