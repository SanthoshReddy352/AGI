import { useState } from "react";
import { useNavigate, useOutletContext } from "react-router-dom";
import { createProject, deleteProject } from "../api.js";

// Project gallery: a card per project + a "New project" card. Each project owns
// dedicated, layered memory; opening one shows its chats and memory panel.
export default function ProjectsView() {
  const { projects, refreshProjects, confirmAction } = useOutletContext();
  const [creating, setCreating] = useState(false);
  const navigate = useNavigate();

  async function removeProject(p) {
    if (!(await confirmAction?.(`Delete “${p.name}”? Its chats are unfiled (kept); its memory is removed.`, "Delete project"))) return;
    await deleteProject(p.id);
    refreshProjects?.();
  }

  return (
    <>
      <header className="flex items-center px-6 h-12 border-b border-line dark:border-night-line">
        <h1 className="font-serif text-lg">Projects</h1>
      </header>
      <main className="flex-1 overflow-y-auto px-6 py-6">
        <div className="max-w-4xl mx-auto">
          <p className="text-ink-soft dark:text-night-faint mb-5 text-[14px]">
            Group related chats into a project with its own dedicated memory — context stays
            put and never mixes with casual tasks.
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            <button onClick={() => setCreating(true)}
              className="h-36 rounded-2xl border border-dashed border-line dark:border-night-line grid place-items-center text-ink-soft dark:text-night-faint hover:border-brand hover:text-brand-deep transition">
              <div className="text-center">
                <div className="mx-auto mb-2 h-9 w-9 rounded-full bg-brand-wash dark:bg-night-panel grid place-items-center text-brand-deep">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M12 5v14M5 12h14" /></svg>
                </div>
                New project
              </div>
            </button>

            {projects.map((p) => (
              <div key={p.id} className="group relative">
                <button onClick={() => navigate(`/projects/${p.id}`)}
                  className="h-36 w-full text-left rounded-2xl border border-line dark:border-night-line bg-paper-panel dark:bg-night-panel p-4 hover:shadow-soft transition flex flex-col">
                  <div className="h-9 w-9 rounded-xl bg-brand-wash dark:bg-night-soft grid place-items-center text-brand-deep mb-2">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M3 7a2 2 0 0 1 2-2h4l2 2.5h8a2 2 0 0 1 2 2V18a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z" /></svg>
                  </div>
                  <div className="font-medium truncate pr-6">{p.name}</div>
                  <div className="text-[13px] text-ink-faint dark:text-night-faint line-clamp-2 flex-1">
                    {p.description || "No description"}
                  </div>
                  <div className="text-[12px] text-ink-faint dark:text-night-faint mt-1">
                    {p.chat_count} {p.chat_count === 1 ? "chat" : "chats"}
                  </div>
                </button>
                <button onClick={(e) => { e.stopPropagation(); removeProject(p); }} title="Delete project"
                  className="absolute top-3 right-3 h-7 w-7 grid place-items-center rounded-full text-ink-faint hover:text-brand-deep hover:bg-paper-sink dark:hover:bg-night-soft opacity-0 group-hover:opacity-100 transition">
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M3 6h18M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" /></svg>
                </button>
              </div>
            ))}
          </div>
        </div>
      </main>

      {creating && (
        <NewProjectModal
          onClose={() => setCreating(false)}
          onCreated={(p) => { setCreating(false); refreshProjects?.(); if (p?.id) navigate(`/projects/${p.id}`); }}
        />
      )}
    </>
  );
}

function NewProjectModal({ onClose, onCreated }) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit() {
    if (!name.trim() || busy) return;
    setBusy(true);
    const r = await createProject(name.trim(), description.trim());
    onCreated(r?.project);
  }

  return (
    <div className="fixed inset-0 z-40 grid place-items-center bg-black/40 p-4" onClick={onClose}>
      <div className="w-[460px] max-w-full rounded-2xl bg-paper-panel dark:bg-night-panel border border-line dark:border-night-line shadow-pop p-5 animate-rise"
           onClick={(e) => e.stopPropagation()}>
        <h3 className="font-serif text-lg mb-3">New project</h3>
        <label className="block text-[13px] text-ink-soft dark:text-night-faint mb-1">Name</label>
        <input autoFocus value={name} onChange={(e) => setName(e.target.value)}
               onKeyDown={(e) => { if (e.key === "Enter") submit(); }}
               placeholder="e.g. Rooftop Garden"
               className="w-full rounded-lg px-3 py-2 mb-3 bg-paper-soft dark:bg-night border border-line dark:border-night-line outline-none focus:border-brand" />
        <label className="block text-[13px] text-ink-soft dark:text-night-faint mb-1">
          What's this project about? <span className="text-ink-faint">(optional — guides the assistant)</span>
        </label>
        <textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={3}
               placeholder="A short brief so I always keep the right context."
               className="w-full rounded-lg px-3 py-2 bg-paper-soft dark:bg-night border border-line dark:border-night-line outline-none focus:border-brand resize-none" />
        <div className="flex justify-end gap-2 mt-4">
          <button onClick={onClose} className="px-4 py-2 rounded-lg text-ink-soft dark:text-night-ink hover:bg-paper-soft dark:hover:bg-night-soft">Cancel</button>
          <button onClick={submit} disabled={!name.trim() || busy}
                  className="px-4 py-2 rounded-lg bg-brand text-white hover:bg-brand-deep disabled:opacity-50">Create</button>
        </div>
      </div>
    </div>
  );
}
