import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { AlertTriangle, RotateCw } from 'lucide-react';
import { apiRequest, getApiErrorMessage } from '../../api/client';
import { useAuth } from '../../auth/useAuth';
import Sidebar from '../../components/Sidebar';
import Navbar from '../../components/Navbar';
import OverviewTab from './OverviewTab';
import AutoModTab from './AutoModTab';
import SettingsTab from './SettingsTab';
import ModerationTab from './ModerationTab';
import EconomyTab from './EconomyTab';
import MembersTab from './MembersTab';
import AuditLogsTab from './AuditLogsTab';

const SNOWFLAKE = /^[1-9]\d{0,19}$/;

export default function GuildDashboard() {
  const { guildId } = useParams();
  const navigate = useNavigate();
  const { token } = useAuth();
  const [guild, setGuild] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [currentTab, setCurrentTab] = useState('overview');
  const [retryCount, setRetryCount] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    Promise.resolve()
      .then(() => {
        if (controller.signal.aborted) return null;
        if (!guildId || !SNOWFLAKE.test(guildId)) {
          setGuild(null);
          setError('O identificador deste servidor é inválido.');
          return null;
        }
        setLoading(true);
        setError(null);
        setGuild(null);
        return apiRequest(`/guilds/${encodeURIComponent(guildId)}`, { token, signal: controller.signal });
      })
      .then((data) => {
        if (!controller.signal.aborted && data !== null) setGuild(data);
      })
      .catch((failure) => {
        if (!controller.signal.aborted) setError(getApiErrorMessage(failure));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [guildId, token, retryCount]);

  let content;
  if (loading || (!error && guild?.id !== guildId)) {
    content = <p role="status" className="rounded-2xl border border-bn-border bg-bn-card p-8 text-sm text-bn-muted">Carregando dados do servidor…</p>;
  } else if (error) {
    content = (
      <div className="max-w-2xl rounded-2xl border border-red-500/30 bg-bn-card p-6">
        <div className="flex items-start gap-3"><AlertTriangle className="mt-0.5 h-5 w-5 text-red-300" /><div><h1 className="font-bold text-white">Não foi possível abrir este servidor</h1><p role="alert" className="mt-2 text-sm text-red-200">{error}</p></div></div>
        <div className="mt-5 flex flex-wrap gap-3"><button onClick={() => setRetryCount((value) => value + 1)} className="inline-flex items-center gap-2 rounded-xl bg-bn-green px-4 py-2 text-sm font-semibold text-bn-dark"><RotateCw className="h-4 w-4" /> Tentar novamente</button><button onClick={() => navigate('/servers')} className="rounded-xl border border-bn-border px-4 py-2 text-sm text-white">Voltar aos servidores</button></div>
      </div>
    );
  } else if (!guild) {
    content = <p role="alert" className="rounded-2xl border border-bn-border bg-bn-card p-6 text-sm text-bn-muted">Servidor indisponível.</p>;
  } else {
    switch (currentTab) {
      case 'overview': content = <OverviewTab guildId={guildId} token={token} setCurrentTab={setCurrentTab} />; break;
      case 'settings': content = <SettingsTab guildId={guildId} token={token} />; break;
      case 'automod': content = <AutoModTab guildId={guildId} token={token} />; break;
      case 'moderation': content = <ModerationTab guildId={guildId} token={token} />; break;
      case 'economy': content = <EconomyTab guildId={guildId} token={token} />; break;
      case 'members': content = <MembersTab guildId={guildId} token={token} />; break;
      case 'logs': content = <AuditLogsTab guildId={guildId} token={token} />; break;
      default: content = <OverviewTab guildId={guildId} token={token} setCurrentTab={setCurrentTab} />;
    }
  }

  return (
    <div className="flex min-h-screen bg-bn-dark">
      <Sidebar currentTab={currentTab} setCurrentTab={setCurrentTab} guild={guild} />
      <div className="flex min-w-0 flex-1 flex-col">
        <Navbar guildName={guild?.name} />
        <main className="flex-1 overflow-y-auto p-5 md:p-8"><div key={`${guildId}:${currentTab}`}>{content}</div></main>
      </div>
    </div>
  );
}
