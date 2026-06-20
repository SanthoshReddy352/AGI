import { useEffect, useState } from "react";
import { checkUpdate, applyUpdate } from "../api.js";

// Slim top bar that appears only when a newer Namma Agent version is published on
// GitHub. "Update now" triggers the detached updater (POST /api/update/apply),
// which closes this app, pulls + reinstalls + rebuilds, and relaunches.
// "Later" hides the bar for that specific version (remembered in localStorage).
const DISMISS_KEY = "namma-update-dismissed";

export default function UpdateBanner() {
  const [info, setInfo] = useState(null);        // { current, latest, html_url, notes }
  const [status, setStatus] = useState("idle");  // idle | updating | error

  useEffect(() => {
    let alive = true;
    checkUpdate().then((r) => {
      if (!alive || !r || !r.update_available) return;
      if (localStorage.getItem(DISMISS_KEY) === r.latest) return; // dismissed this version
      setInfo(r);
    });
    return () => { alive = false; };
  }, []);

  if (!info) return null;

  const dismiss = () => { localStorage.setItem(DISMISS_KEY, info.latest); setInfo(null); };
  const update = async () => {
    setStatus("updating");
    const r = await applyUpdate();
    if (!r || r.started === false) setStatus("error");
    // On success the updater shuts this app down and relaunches it — the
    // "updating" message stays on screen until the window closes.
  };

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2 text-sm bg-brand text-white shadow-sm">
      {status === "updating" ? (
        <span className="font-medium">Updating to {info.latest}… the app will close and reopen automatically.</span>
      ) : status === "error" ? (
        <>
          <span className="font-medium">Couldn’t start the update.</span>
          <span className="opacity-90">Run the updater for your OS — see docs/INSTALL.md.</span>
          <span className="flex-1" />
          <button onClick={dismiss} className="px-2 py-1 rounded-md text-white/90 hover:bg-white/10">Dismiss</button>
        </>
      ) : (
        <>
          <span className="font-semibold">Update available</span>
          <span className="opacity-90">
            Namma Agent {info.latest} is ready{info.current ? ` (you have ${info.current})` : ""}.
          </span>
          {info.html_url && (
            <a href={info.html_url} target="_blank" rel="noreferrer"
               className="underline opacity-90 hover:opacity-100">What’s new</a>
          )}
          <span className="flex-1" />
          <button onClick={update}
                  className="px-3 py-1 rounded-md bg-white text-brand-deep font-medium hover:bg-white/90">
            Update now
          </button>
          <button onClick={dismiss} className="px-2 py-1 rounded-md text-white/90 hover:bg-white/10">Later</button>
        </>
      )}
    </div>
  );
}
