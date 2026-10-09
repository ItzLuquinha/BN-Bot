import React, { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { useAuth } from '../../AuthContext';
import Sidebar from '../../components/Sidebar';
import Navbar from '../../components/Navbar';
import OverviewTab from './OverviewTab';
import AutoModTab from './AutoModTab';

export default function GuildDashboard() {
  const { guildId } = useParams();
  const { token } = useAuth();
  const [guild, setGuild] = useState(null);
  const [currentTab, setCurrentTab] = useState("overview");

  useEffect(() => {
    const fetchGuild = async () => {
      try {
        const res = await fetch(`http://localhost:8000/api/v1/guilds/${guildId}`, {
          headers: { Authorization: `Bearer ${token}` }
        });
        if (res.ok) {
          const data = await res.json();
          setGuild(data);
        }
      } catch (err) {
        console.error(err);
      }
    };
    fetchGuild();
  }, [guildId, token]);

  return (
    <div className="min-h-screen bg-bn-dark flex">
      {/* Sidebar Lateral */}
      <Sidebar 
        currentTab={currentTab} 
        setCurrentTab={setCurrentTab} 
        guild={guild} 
      />

      {/* Conteúdo Principal com Scroll Próprio */}
      <div className="flex-1 flex flex-col min-w-0">
        <Navbar guildName={guild?.name} />
        
        <main className="flex-1 p-8 overflow-y-auto">
          {currentTab === "overview" && <OverviewTab setCurrentTab={setCurrentTab} />}
          {currentTab === "automod" && <AutoModTab />}
          {currentTab === "settings" && <div className="text-white">Aba de Configurações em construção...</div>}
          {currentTab === "moderation" && <div className="text-white">Aba de Moderação em construção...</div>}
          {currentTab === "economy" && <div className="text-white">Aba de Economia em construção...</div>}
        </main>
      </div>
    </div>
  );
}