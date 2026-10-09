import React, { useState } from 'react';
import { ShieldAlert, Save } from 'lucide-react';

export default function AutoModTab() {
  const [invitesBlocked, setInvitesBlocked] = useState(true);
  const [massMentions, setMassMentions] = useState(true);
  const [mentionThreshold, setMentionThreshold] = useState(5);
  const [mentionAction, setMentionAction] = useState("Mute");

  return (
    <div className="max-w-3xl">
      <div className="mb-8">
        <h2 className="text-2xl font-bold text-white flex items-center gap-2">
          <ShieldAlert className="w-6 h-6 text-bn-green" />
          Auto Moderation
        </h2>
        <p className="text-sm text-bn-muted mt-1">
          Detecte e puna automaticamente comportamentos indevidos, links e spam de menções.
        </p>
      </div>

      <div className="space-y-6">
        {/* Toggle 1: Discord Invites */}
        <div className="p-6 rounded-2xl bg-bn-card border border-bn-border flex items-center justify-between">
          <div>
            <h4 className="font-bold text-white text-sm">Bloquear Convites de Discord</h4>
            <p className="text-xs text-bn-muted mt-0.5">Apaga links de outros servidores e avisa o autor.</p>
          </div>
          <button 
            onClick={() => setInvitesBlocked(!invitesBlocked)}
            className={`w-12 h-6 flex items-center rounded-full p-1 transition-colors cursor-pointer ${
              invitesBlocked ? 'bg-bn-green' : 'bg-bn-dark'
            }`}
          >
            <div className={`bg-white w-4 h-4 rounded-full transition-transform ${invitesBlocked ? 'translate-x-6' : 'translate-x-0'}`} />
          </button>
        </div>

        {/* Toggle 2: Mass Mentions */}
        <div className="p-6 rounded-2xl bg-bn-card border border-bn-border space-y-5">
          <div className="flex items-center justify-between">
            <div>
              <h4 className="font-bold text-white text-sm">Proteção contra Mass Mention</h4>
              <p className="text-xs text-bn-muted mt-0.5">Detecta e pune usuários que marcam muitas pessoas de uma só vez.</p>
            </div>
            <button 
              onClick={() => setMassMentions(!massMentions)}
              className={`w-12 h-6 flex items-center rounded-full p-1 transition-colors cursor-pointer ${
                massMentions ? 'bg-bn-blue' : 'bg-bn-dark'
              }`}
            >
              <div className={`bg-white w-4 h-4 rounded-full transition-transform ${massMentions ? 'translate-x-6' : 'translate-x-0'}`} />
            </button>
          </div>

          {massMentions && (
            <div className="pt-4 border-t border-bn-border/60 grid grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-semibold text-bn-muted uppercase mb-1.5">Limite de Menções</label>
                <input 
                  type="number"
                  value={mentionThreshold}
                  onChange={(e) => setMentionThreshold(e.target.value)}
                  className="w-full bg-bn-dark border border-bn-border rounded-xl px-3.5 py-2 text-white text-sm focus:outline-none focus:border-bn-blue"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-bn-muted uppercase mb-1.5">Ação Aplicada</label>
                <select 
                  value={mentionAction}
                  onChange={(e) => setMentionAction(e.target.value)}
                  className="w-full bg-bn-dark border border-bn-border rounded-xl px-3.5 py-2 text-white text-sm focus:outline-none focus:border-bn-blue"
                >
                  <option value="Delete">Apenas Apagar Mensagem</option>
                  <option value="Mute">Silenciar (Mute / Timeout)</option>
                  <option value="Kick">Expulsar (Kick)</option>
                  <option value="Ban">Banir</option>
                </select>
              </div>
            </div>
          )}
        </div>

        <button className="flex items-center gap-2 px-6 py-2.5 rounded-xl bg-bn-green hover:bg-bn-greenHover text-bn-dark font-bold text-sm transition-all shadow-glow-green cursor-pointer">
          <Save className="w-4 h-4" />
          <span>Salvar Alterações</span>
        </button>
      </div>
    </div>
  );
}