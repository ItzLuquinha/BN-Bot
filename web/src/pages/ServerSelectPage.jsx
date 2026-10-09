import React, { useEffect, useState } from 'react';
import { useAuth } from '../AuthContext';
import { useNavigate } from 'react-router-dom';
import Navbar from '../components/Navbar';
import { Server, ArrowRight } from 'lucide-react';

export default function ServerSelectPage() {
  const { token } = useAuth();
  const [guilds, setGuilds] = useState([]);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    const fetchGuilds = async () => {
      try {
        const res = await fetch('http://localhost:8000/api/v1/guilds', {
          headers: { Authorization: `Bearer ${token}` }
        });
        if (res.ok) {
          const data = await res.json();
          setGuilds(data);
        }
      } catch (err) {
        console.error("Erro ao buscar servidores:", err);
      } finally {
        setLoading(false);
      }
    };
    fetchGuilds();
  }, [token]);

  return (
    <div className="min-h-screen bg-bn-dark flex flex-col">
      <Navbar />

      <main className="flex-1 max-w-5xl mx-auto px-6 py-12 w-full">
        <h1 className="text-3xl font-extrabold text-white mb-2">Selecione um Servidor</h1>
        <p className="text-bn-muted text-sm mb-8">Escolha o servidor que você deseja gerenciar no painel.</p>

        {loading ? (
          <div className="text-center py-20 text-bn-muted animate-pulse">Carregando servidores cadastrados...</div>
        ) : guilds.length === 0 ? (
          <div className="p-12 text-center rounded-2xl bg-bn-card border border-bn-border text-bn-muted">
            Nenhum servidor ativo com o BN Bot encontrado na sua conta.
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
            {guilds.map((guild) => (
              <div 
                key={guild.id}
                onClick={() => navigate(`/dashboard/${guild.id}`)}
                className="p-5 rounded-2xl bg-bn-card border border-bn-border hover:border-bn-green/50 hover:bg-bn-cardHover transition-all cursor-pointer flex items-center justify-between group"
              >
                <div className="flex items-center gap-3.5">
                  {guild.icon_url ? (
                    <img src={guild.icon_url} alt="" className="w-12 h-12 rounded-xl" />
                  ) : (
                    <div className="w-12 h-12 rounded-xl bg-bn-border flex items-center justify-center">
                      <Server className="w-6 h-6 text-bn-green" />
                    </div>
                  )}
                  <div>
                    <h3 className="font-bold text-white text-base group-hover:text-bn-green transition-colors">{guild.name}</h3>
                    <span className="text-[11px] text-bn-muted">ID: {guild.id}</span>
                  </div>
                </div>
                <ArrowRight className="w-5 h-5 text-bn-muted group-hover:text-bn-green group-hover:translate-x-1 transition-all" />
              </div>
            ))}
          </div>
        )}
      </main>
    </div>
  );
}