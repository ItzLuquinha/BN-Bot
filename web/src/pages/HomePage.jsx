import { useAuth } from '../auth/useAuth';
import { useNavigate } from 'react-router-dom';
import { 
  Shield, Sparkles, Zap, ArrowRight, LayoutDashboard, 
  Database, LogOut, User, ExternalLink, Bot
} from 'lucide-react';

export default function HomePage() {
  const { user, isAuthenticated, loading, login, logout } = useAuth();
  const navigate = useNavigate();

  const getAvatarUrl = (user) => {
    if (!user || !user.avatar) return null;
    return `https://cdn.discordapp.com/avatars/${user.id}/${user.avatar}.png`;
  };

  return (
    <div className="min-h-screen flex flex-col bg-bn-dark relative overflow-hidden select-none">

      <div className="absolute -top-40 -left-40 w-[30rem] h-[30rem] bg-bn-green rounded-full blur-[100px] pointer-events-none animate-blob-green" />
      <div className="absolute top-1/3 -right-40 w-[32rem] h-[32rem] bg-bn-blue rounded-full blur-[110px] pointer-events-none animate-blob-blue" />
      <div className="absolute -bottom-40 left-1/3 w-[28rem] h-[28rem] bg-bn-gold rounded-full blur-[90px] pointer-events-none animate-blob-gold" />

      
      <header className="border-b border-bn-border/60 bg-bn-dark/80 backdrop-blur-md sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-6 h-20 flex items-center justify-between">
          
          <div className="flex items-center gap-3">
            <div className="w-11 h-11 rounded-xl bg-bn-card flex items-center justify-center border border-bn-border relative shadow-inner">
              <span className="font-extrabold text-lg text-white">B</span>
              <span className="font-extrabold text-lg text-bn-green">N</span>
              <span className="absolute -top-1 -right-1 text-bn-gold text-xs">✦</span>
            </div>
            <div>
              <span className="font-bold text-xl tracking-tight text-white">
                BN <span className="text-bn-green">Bot</span>
              </span>
              <span className="block text-[10px] text-bn-muted tracking-widest uppercase font-semibold">
                Web Dashboard
              </span>
            </div>
          </div>

          
          <div className="flex items-center gap-4">
            {loading ? (
              <span className="text-xs text-bn-muted animate-pulse">Verificando sessão...</span>
            ) : isAuthenticated ? (
              <div className="flex items-center gap-3">
                
                <button
                  onClick={() => navigate('/servers')}
                  className="hidden sm:flex items-center gap-2 px-4 py-2 rounded-xl bg-bn-green/15 text-bn-green border border-bn-green/30 hover:bg-bn-green hover:text-bn-dark font-bold text-xs transition-all cursor-pointer"
                >
                  <LayoutDashboard className="w-3.5 h-3.5" />
                  <span>Meus Servidores</span>
                </button>

                
                <div className="flex items-center gap-3 bg-bn-card border border-bn-border px-3.5 py-1.5 rounded-xl shadow-sm">
                  {getAvatarUrl(user) ? (
                    <img src={getAvatarUrl(user)} alt="Avatar" className="w-8 h-8 rounded-full border border-bn-green" />
                  ) : (
                    <div className="w-8 h-8 rounded-full bg-bn-border flex items-center justify-center">
                      <User className="w-4 h-4 text-white" />
                    </div>
                  )}
                  <div className="text-left">
                    <p className="text-xs font-bold text-white leading-none">{user.username}</p>
                    <span className="text-[10px] uppercase font-bold text-bn-green">
                      {user.system_role}
                    </span>
                  </div>
                </div>

                
                <button 
                  onClick={logout}
                  title="Sair da Conta"
                  className="p-2.5 rounded-xl bg-bn-card border border-bn-border hover:border-red-500/50 hover:text-red-400 text-bn-muted transition-colors cursor-pointer"
                >
                  <LogOut className="w-4 h-4" />
                </button>
              </div>
            ) : (
              <button 
                onClick={login}
                className="flex items-center gap-2 px-5 py-2.5 rounded-xl bg-bn-blue hover:bg-bn-blueHover text-white font-medium text-sm transition-all shadow-glow-blue cursor-pointer"
              >
                <span>Login com Discord</span>
                <ArrowRight className="w-4 h-4" />
              </button>
            )}
          </div>
        </div>
      </header>

      
      <main className="flex-1 max-w-7xl mx-auto px-6 py-16 flex flex-col justify-center items-center text-center z-10">
        
        <div className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full bg-bn-card border border-bn-border text-bn-gold text-xs font-semibold mb-8 shadow-sm">
          <Sparkles className="w-3.5 h-3.5" />
          <span>Gestão Inteligente & Automação para Discord</span>
        </div>

        
        <h1 className="text-5xl md:text-6xl font-extrabold tracking-tight text-white max-w-4xl leading-[1.15]">
          O controle do seu servidor nas suas mãos com o{' '}
          <span className="text-transparent bg-clip-text bg-gradient-to-r from-bn-green via-bn-gold to-bn-blue">
            BN Bot
          </span>
        </h1>

        
        <p className="mt-6 text-lg text-bn-muted max-w-2xl leading-relaxed">
          Configure regras de AutoMod, gerencie economia personalizada, acompanhe métricas de atividade e puna infratores com um painel web intuitivo em tempo real.
        </p>

        
        <div className="mt-10 flex flex-wrap gap-4 justify-center items-center">
          {isAuthenticated ? (
            <button 
              onClick={() => navigate('/servers')}
              className="flex items-center gap-3 px-8 py-3.5 rounded-xl bg-bn-green hover:bg-bn-greenHover text-bn-dark font-extrabold text-base transition-all shadow-glow-green cursor-pointer hover:scale-105"
            >
              <LayoutDashboard className="w-5 h-5" />
              <span>Acessar Meus Servidores</span>
            </button>
          ) : (
            <button 
              onClick={login}
              className="flex items-center gap-3 px-8 py-3.5 rounded-xl bg-bn-green hover:bg-bn-greenHover text-bn-dark font-extrabold text-base transition-all shadow-glow-green cursor-pointer hover:scale-105"
            >
              <Bot className="w-5 h-5" />
              <span>Conectar com Discord</span>
            </button>
          )}

          <a 
            href="https://discord.com" 
            target="_blank" 
            rel="noreferrer"
            className="flex items-center gap-2 px-6 py-3.5 rounded-xl bg-bn-card border border-bn-border hover:border-bn-border/80 text-white font-medium text-sm transition-all hover:bg-bn-cardHover cursor-pointer"
          >
            <span>Servidor de Suporte</span>
            <ExternalLink className="w-4 h-4 text-bn-muted" />
          </a>
        </div>

        
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mt-20 w-full text-left">
          
          <div className="p-6 rounded-2xl bg-bn-card border border-bn-border hover:border-bn-green/40 transition-all hover:bg-bn-cardHover group">
            <div className="w-12 h-12 rounded-xl bg-bn-green/10 text-bn-green flex items-center justify-center mb-5 group-hover:scale-110 transition-transform">
              <Shield className="w-6 h-6" />
            </div>
            <h3 className="font-bold text-lg text-white mb-2">AutoMod Avançado</h3>
            <p className="text-sm text-bn-muted leading-relaxed">
              Bloqueio automático de convites, proteção contra mass mention, filtros de palavras proibidas e punições instantâneas.
            </p>
          </div>

          
          <div className="p-6 rounded-2xl bg-bn-card border border-bn-border hover:border-bn-gold/40 transition-all hover:bg-bn-cardHover group">
            <div className="w-12 h-12 rounded-xl bg-bn-gold/10 text-bn-gold flex items-center justify-center mb-5 group-hover:scale-110 transition-transform">
              <Zap className="w-6 h-6" />
            </div>
            <h3 className="font-bold text-lg text-white mb-2">Economia & Níveis</h3>
            <p className="text-sm text-bn-muted leading-relaxed">
              Loja de itens customizados, sistema bancário com rendimento, missões diárias, rankings de XP e recompensas para membros.
            </p>
          </div>

          
          <div className="p-6 rounded-2xl bg-bn-card border border-bn-border hover:border-bn-blue/40 transition-all hover:bg-bn-cardHover group">
            <div className="w-12 h-12 rounded-xl bg-bn-blue/10 text-bn-blue flex items-center justify-center mb-5 group-hover:scale-110 transition-transform">
              <Database className="w-6 h-6" />
            </div>
            <h3 className="font-bold text-lg text-white mb-2">Auditoria em Nuvem</h3>
            <p className="text-sm text-bn-muted leading-relaxed">
              Histórico seguro de todas as alterações feitas no dashboard, relatórios de atividades e sincronização direta no banco de dados.
            </p>
          </div>
        </div>
      </main>

      
      <footer className="border-t border-bn-border/60 py-8 text-center text-xs text-bn-muted z-10">
        <p>© 2026 BN Bot. Todos os direitos reservados.</p>
      </footer>
    </div>
  );
}