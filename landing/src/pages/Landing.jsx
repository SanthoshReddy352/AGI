import Nav, { scrollToId } from "../components/Nav.jsx";
import Footer from "../components/Footer.jsx";
import { LogoMark, Arrow, Check, Lines, Brain, Graph, Cap, Chat, Doc, Search } from "../components/icons.jsx";

const sc = (id) => (e) => { e.preventDefault(); scrollToId(id); };

const Mega = (
  <div className="navx__drop" key="mega">
    <button className="navx__link" aria-haspopup="true" aria-expanded="false">
      Capabilities <svg className="caret" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"><path d="M6 9l6 6 6-6" /></svg>
    </button>
    <div className="navx__mega" role="menu">
      <div className="navx__mega-grid">
        <a className="mega-item" href="#capabilities" onClick={sc("capabilities")}><span className="ico"><Lines size={20} /></span><div><b>Tools</b><span>~85 native actions</span></div></a>
        <a className="mega-item" href="#memory" onClick={sc("memory")}><span className="ico pine"><Brain size={20} /></span><div><b>Memory</b><span>Facts that persist</span></div></a>
        <a className="mega-item" href="#graph" onClick={sc("graph")}><span className="ico"><Graph size={20} /></span><div><b>Knowledge graph</b><span>Optional, via Cognee</span></div></a>
        <a className="mega-item" href="#learn" onClick={sc("learn")}><span className="ico pine"><Cap size={20} /></span><div><b>Learning Room</b><span>One module at a time</span></div></a>
      </div>
      <div className="navx__mega-foot"><span className="muted" style={{ fontSize: "var(--fs-small)" }}>One agent, any brain, your machine</span><a href="#capabilities" onClick={sc("capabilities")}>Explore →</a></div>
    </div>
  </div>
);

const navItems = [
  { id: "top", label: "Overview" },
  { mega: true },
  { id: "providers", label: "Providers", spy: true },
  { to: "/docs", label: "Docs" },
];
const mobileItems = [
  { id: "capabilities", label: "Capabilities" },
  { id: "graph", label: "Knowledge graph" },
  { id: "providers", label: "Providers" },
  { to: "/docs", label: "Docs" },
  { id: "start", label: "Get started" },
];

export default function Landing() {
  return (
    <>
      <Nav items={navItems} mega={Mega} showCmdk cta={{ id: "start", label: "Run it" }} mobileItems={mobileItems} />

      {/* command palette */}
      <div className="scrim" data-scrim></div>
      <div className="palette" role="dialog" aria-label="Command palette">
        <div className="palette__input">
          <Search size={18} /><input type="text" placeholder="Jump to a section..." aria-label="Search" />
          <kbd style={{ fontFamily: "var(--font-mono)", fontSize: "11px", color: "var(--ink-faint)" }}>esc</kbd>
        </div>
        <div className="palette__list">
          <div className="palette__item" data-go="#capabilities" aria-selected="true"><span className="ico"><Lines size={15} /></span> Capabilities <span className="meta">section</span></div>
          <div className="palette__item" data-go="#graph"><span className="ico"><Graph size={15} /></span> Knowledge graph <span className="meta">section</span></div>
          <div className="palette__item" data-go="#providers"><span className="ico"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="3" /></svg></span> Providers <span className="meta">section</span></div>
          <div className="palette__item" data-go="#start"><span className="ico"><Arrow size={15} /></span> Get started <span className="meta">section</span></div>
        </div>
      </div>

      <main>
        {/* HERO */}
        <header className="na-hero">
          <span className="orb" aria-hidden="true"></span>
          <div>
            <span className="badge" data-reveal><span className="dot pulse"></span> Cloud-only, runs anywhere Python does</span>
            <h1 className="display" data-reveal style={{ "--reveal-delay": "80ms" }}>A personal AI assistant you actually run yourself.</h1>
            <p className="lead" data-reveal style={{ "--reveal-delay": "160ms" }}>Namma Agent wraps one API call in everything that makes it an agent: a tool-calling loop, memory that lasts, document intelligence, and a learning room. Bring any brain, keep your data on your machine.</p>
            <ul className="lede-list" data-reveal style={{ "--reveal-delay": "220ms" }}>
              <li><Check /> Around 85 tools the model calls natively, no intent regexes.</li>
              <li><Check /> Swap Anthropic for a local Ollama model with one config key.</li>
            </ul>
            <div className="row" data-reveal style={{ "--reveal-delay": "300ms", marginTop: "var(--s-5)", gap: "var(--s-4)" }}>
              <a href="#start" onClick={sc("start")} className="btn btn--primary btn--lg" data-magnetic="0.4">Get started<Arrow /></a>
              <button className="btn btn--secondary btn--lg" data-cmdk-open>Browse capabilities</button>
            </div>
          </div>

          <div data-reveal="right">
            <div className="console tilt" data-tilt="4">
              <div className="console__bar"><i></i><i></i><i></i><span className="who">namma · one turn</span></div>
              <div className="console__body">
                <div className="msg">
                  <span className="from">You</span>
                  <div className="bubble user">Find last week's invoices, total them, and remind me to send the report on Friday.</div>
                </div>
                <div className="msg">
                  <span className="from">Namma · running tools</span>
                  <div className="toolcalls">
                    <span className="toolcall"><span className="tick"><Check size={12} /></span>find_files</span>
                    <span className="toolcall"><span className="tick"><Check size={12} /></span>read_document</span>
                    <span className="toolcall run"><span className="tick"><span className="pixel-loader" style={{ "--pixel": "3px" }}><i></i><i></i><i></i><i></i></span></span>add_reminder</span>
                  </div>
                </div>
                <div className="msg">
                  <span className="from">Namma</span>
                  <div className="bubble agent">Found 6 invoices from last week totalling $4,820. I set a reminder for Friday at 9am to send the report.<span className="caret" aria-hidden="true"></span></div>
                </div>
              </div>
            </div>
          </div>
        </header>

        {/* TRUST MARQUEE */}
        <div className="shell" data-reveal>
          <div className="marquee-mask">
            <div className="marquee" aria-hidden="true">
              {["Anthropic", "OpenAI", "Google", "Ollama", "LM Studio", "MCP", "Cognee", "Anthropic", "OpenAI", "Google", "Ollama", "LM Studio", "MCP", "Cognee"].map((n, i) => (
                <span key={i} style={{ fontFamily: "var(--font-display)", fontSize: "1.25rem", color: "var(--ink-faint)" }}>{n}</span>
              ))}
            </div>
          </div>
        </div>

        {/* CAPABILITIES BENTO */}
        <section id="capabilities" className="section shell">
          <div className="section-head" data-reveal><span className="eyebrow">What's inside</span><h2>An agent, not a chat box.</h2></div>
          <div className="bento" data-reveal-group data-stagger="90">
            <div className="flex-col tile-accent col-2 flow-sweep" data-reveal data-ambient>
              <div className="b-head"><span className="ico" style={{ background: "rgba(255,255,255,.18)", color: "#fff" }}><Lines /></span> The agent loop</div>
              <div className="b-big">One loop, end to end</div>
              <div className="b-foot">Generate, run tools, loop, answer. The model calls tools natively and streams as it goes.</div>
            </div>
            <div className="flex-col" data-reveal>
              <div className="b-head"><span className="ico"><Lines /></span> Tools</div>
              <div className="b-big" style={{ fontSize: "2.4rem" }}>~85</div>
              <p className="muted" style={{ fontSize: "var(--fs-small)", marginTop: "auto" }}>Files, shell, web, vision, scheduler, and more.</p>
            </div>
            <div className="flex-col row-2" id="memory" data-reveal>
              <div className="b-head"><Brain /> Memory that lasts</div>
              <p className="muted" style={{ fontSize: "var(--fs-small)", marginTop: "6px" }}>Facts, notes, and session summaries in one SQLite store, recalled across days.</p>
              <div className="chips" style={{ marginTop: "auto" }}><span className="chip-tag solid">remember</span><span className="chip-tag">recall</span><span className="chip-tag">summarize</span></div>
            </div>
            <div className="flex-col tile-ink" data-reveal data-ambient>
              <div className="b-head"><span className="ico" style={{ background: "rgba(255,255,255,.12)", color: "#fff" }}><Chat /></span> Voice & Telegram</div>
              <div className="b-big" style={{ fontSize: "1.85rem" }}>Talk anywhere</div>
              <div className="b-foot">Browser-native voice, plus a Telegram bridge for your phone.</div>
            </div>
            <div className="flex-col col-2" data-reveal>
              <div className="b-head"><Doc /> Projects with document intelligence</div>
              <p className="muted" style={{ fontSize: "var(--fs-small)", margin: "8px 0 auto" }}>Give each project a document shelf. Every upload is screened for prompt injection, chunked, and indexed, so answers come back with file and section citations.</p>
              <div className="row" style={{ justifyContent: "space-between", marginTop: "var(--s-4)" }}><span className="muted" style={{ fontSize: "var(--fs-small)" }}>Indexed and grounded</span><b style={{ fontSize: "var(--fs-small)" }}>25 files / project</b></div>
            </div>
          </div>
        </section>

        {/* KNOWLEDGE GRAPH */}
        <section id="graph" className="section shell">
          <div className="graph-wrap">
            <div data-reveal="left">
              <span className="eyebrow"><span className="pixel-mark" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i></span>&nbsp; Optional memory</span>
              <h2 style={{ margin: "var(--s-3) 0 var(--s-4)" }}>It remembers how things connect.</h2>
              <p className="muted" style={{ maxWidth: "46ch" }}>Turn on the optional Cognee layer and your facts stop being a flat list. They become a graph: people, files, and ideas linked by how they relate, so the assistant can follow a thread instead of guessing. It runs containerized and reaches the agent over MCP, adding no Python dependencies.</p>
              <ul className="lede-list">
                <li><Check /> Semantic search over everything it has learned.</li>
                <li><Check /> Entities and relationships, not just keywords.</li>
                <li><Check /> One command to set up, Docker is all you need.</li>
              </ul>
              <div className="row" style={{ marginTop: "var(--s-6)", gap: "var(--s-3)" }}><span className="badge badge--pine"><span className="dot"></span> Cognee</span><span className="badge badge--quiet"><span className="dot"></span> via MCP</span><span className="badge badge--quiet"><span className="dot"></span> no extra deps</span></div>
            </div>
            <div className="graph-card" data-reveal="right" aria-hidden="true">
              <svg viewBox="0 0 420 340" fill="none" xmlns="http://www.w3.org/2000/svg">
                <g stroke="var(--line-strong)" strokeWidth="2">
                  <path d="M210 170 L110 80" /><path d="M210 170 L320 90" /><path d="M210 170 L95 250" /><path d="M210 170 L325 245" /><path d="M110 80 L320 90" /><path d="M95 250 L325 245" /><path d="M320 90 L325 245" />
                </g>
                <g className="gnode-float"><circle cx="110" cy="80" r="26" fill="var(--surface-sunken)" stroke="var(--line)" strokeWidth="1.5" /><text x="110" y="84" textAnchor="middle" fontFamily="var(--font-mono)" fontSize="11" fill="var(--ink-muted)">people</text></g>
                <g className="gnode-float b"><circle cx="320" cy="90" r="26" fill="var(--surface-sunken)" stroke="var(--line)" strokeWidth="1.5" /><text x="320" y="94" textAnchor="middle" fontFamily="var(--font-mono)" fontSize="11" fill="var(--ink-muted)">files</text></g>
                <g className="gnode-float c"><circle cx="95" cy="250" r="26" fill="var(--surface-sunken)" stroke="var(--line)" strokeWidth="1.5" /><text x="95" y="254" textAnchor="middle" fontFamily="var(--font-mono)" fontSize="11" fill="var(--ink-muted)">tasks</text></g>
                <g className="gnode-float b"><circle cx="325" cy="245" r="26" fill="var(--surface-sunken)" stroke="var(--line)" strokeWidth="1.5" /><text x="325" y="249" textAnchor="middle" fontFamily="var(--font-mono)" fontSize="11" fill="var(--ink-muted)">notes</text></g>
                <g className="gnode-float"><circle cx="210" cy="170" r="34" fill="var(--accent)" /><text x="210" y="166" textAnchor="middle" fontFamily="var(--font-mono)" fontSize="11" fill="var(--accent-ink)">you</text><text x="210" y="180" textAnchor="middle" fontFamily="var(--font-mono)" fontSize="9" fill="color-mix(in srgb, var(--accent-ink) 75%, transparent)">graph</text></g>
              </svg>
              <div className="pixel-corners" style={{ position: "absolute", inset: 0, pointerEvents: "none" }}></div>
            </div>
          </div>
        </section>

        {/* PROVIDERS */}
        <section id="providers" className="section shell">
          <div className="section-head" data-reveal><span className="eyebrow">One agent, any brain</span><h2>Bring the model you trust.</h2></div>
          <div className="providers" data-reveal-group data-stagger="70">
            <div className="card provider" data-reveal><span className="ico"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M12 3l9 18H3z" /></svg></span><div><b>Anthropic</b><span>Claude, native</span></div></div>
            <div className="card provider" data-reveal><span className="ico"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="9" /><circle cx="12" cy="12" r="3.4" /></svg></span><div><b>OpenAI</b><span>GPT, native</span></div></div>
            <div className="card provider" data-reveal><span className="ico"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M12 12h9a9 9 0 1 1-2.6-6.3" /></svg></span><div><b>Google</b><span>Gemini, native</span></div></div>
            <div className="card provider" data-reveal><span className="ico"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><rect x="4" y="4" width="16" height="16" rx="5" /><circle cx="9.5" cy="11" r="1.3" fill="currentColor" /><circle cx="14.5" cy="11" r="1.3" fill="currentColor" /></svg></span><div><b>Ollama</b><span>Local, no key</span></div></div>
            <div className="card provider" data-reveal><span className="ico"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M4 18V6l8 5 8-5v12" /></svg></span><div><b>LM Studio</b><span>Local, no key</span></div></div>
            <div className="card provider" data-reveal><span className="ico"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M12 3v18M3 12h18" /></svg></span><div><b>OpenAI-compatible</b><span>Any base URL</span></div></div>
          </div>
          <p className="muted" data-reveal style={{ textAlign: "center", marginTop: "var(--s-6)", fontSize: "var(--fs-small)" }}>A provider chain falls back across these automatically when one is down. Local Ollama or LM Studio need no key, for a fully offline setup.</p>
        </section>

        {/* HOW IT WORKS */}
        <section className="section shell">
          <div className="section-head" data-reveal><span className="eyebrow">How a turn works</span><h2>Four steps, on every message.</h2></div>
          <div className="flow" data-reveal-group data-stagger="80">
            <div className="card step-card" data-reveal><div className="n">01</div><h3>Generate</h3><p className="muted" style={{ fontSize: "var(--fs-small)" }}>The model reads the turn and decides what to do.</p></div>
            <div className="card step-card" data-reveal><div className="n">02</div><h3>Run tools</h3><p className="muted" style={{ fontSize: "var(--fs-small)" }}>It calls tools natively. Sensitive ones are approval gated.</p></div>
            <div className="card step-card" data-reveal><div className="n">03</div><h3>Loop</h3><p className="muted" style={{ fontSize: "var(--fs-small)" }}>Results feed back in, and it chains the next step.</p></div>
            <div className="card step-card" data-reveal><div className="n">04</div><h3>Answer</h3><p className="muted" style={{ fontSize: "var(--fs-small)" }}>Tokens stream to the UI as the answer comes together.</p></div>
          </div>
        </section>

        {/* LEARNING ROOM */}
        <section id="learn" className="section shell">
          <div className="suite-grid">
            <div data-reveal="left">
              <span className="eyebrow">Learning Room</span>
              <h2 style={{ margin: "var(--s-3) 0 var(--s-4)" }}>Turn any goal into a path.</h2>
              <p className="muted" style={{ maxWidth: "46ch" }}>Hand it a goal or a syllabus. Namma Agent infers your level, builds a module path, and teaches one module at a time, each in its own chat. It assesses through conversation, keeps a model of how you think, and only advances on an explicit confidence gate.</p>
              <div className="accordion" data-single="true" style={{ marginTop: "var(--s-6)" }}>
                <div className="acc-item open"><button className="acc-head" aria-expanded="true">Recall warm-ups and a running example <span className="plus"></span></button><div className="acc-body"><div><p className="muted">Each module opens by pulling forward what you already know, then carries one example across the whole path.</p></div></div></div>
                <div className="acc-item"><button className="acc-head" aria-expanded="false">Diagrams and simulations, server-rendered <span className="plus"></span></button><div className="acc-body"><div><p className="muted">Inline diagrams, images, and interactive simulations are produced server-side, so nothing extra runs in your browser.</p></div></div></div>
                <div className="acc-item"><button className="acc-head" aria-expanded="false">Gentle Telegram nudges <span className="plus"></span></button><div className="acc-body"><div><p className="muted">Opt in, and it reminds you about topics that have gone quiet, on your phone.</p></div></div></div>
              </div>
            </div>
            <div data-reveal="right">
              <div className="card" style={{ padding: "var(--pad-card)" }}>
                <div style={{ fontFamily: "var(--font-mono)", fontSize: "var(--fs-micro)", letterSpacing: ".1em", textTransform: "uppercase", color: "var(--ink-faint)", marginBottom: "var(--s-4)" }}>Module path</div>
                <div className="steps" style={{ marginBottom: "var(--s-6)" }}><div className="step done"><span className="num"><Check size={14} /></span><span className="lbl">Basics</span></div><span className="line" style={{ background: "var(--accent)" }}></span><div className="step active"><span className="num">2</span><span className="lbl">Core</span></div><span className="line"></span><div className="step"><span className="num">3</span><span className="lbl">Applied</span></div></div>
                <div className="row" style={{ justifyContent: "space-between", marginBottom: "8px" }}><span className="muted" style={{ fontSize: "var(--fs-small)" }}>Confidence</span><b style={{ fontSize: "var(--fs-small)" }}>on track</b></div>
                <div className="bar"><i style={{ "--p": "64%" }}></i></div>
                <div className="av-row" style={{ marginTop: "var(--s-5)" }}><span className="badge badge--quiet"><span className="dot"></span> Socratic hints</span><span className="badge badge--pine" style={{ marginLeft: "8px" }}><span className="dot"></span> learner model</span></div>
              </div>
            </div>
          </div>
        </section>

        {/* QUICKSTART / CTA */}
        <section id="start" className="section shell">
          <div className="quickstart">
            <div data-reveal="left">
              <span className="eyebrow">Get started</span>
              <h2 style={{ margin: "var(--s-3) 0 var(--s-4)" }}>Up and running in a minute.</h2>
              <p className="muted" style={{ maxWidth: "44ch" }}>Install the core, add a key for the provider you want, and open the chat at localhost. The server mode is the most reliable first run, no GUI needed.</p>
              <div className="row" style={{ marginTop: "var(--s-6)", gap: "var(--s-4)" }}>
                <a href="https://github.com/SanthoshReddy352/Namma-Agent" className="btn btn--primary btn--lg" data-magnetic data-toast="success">View on GitHub<Arrow /></a>
                <a href="#/docs" className="btn btn--secondary btn--lg">Read the docs</a>
              </div>
            </div>
            <div data-reveal="right">
              <div className="term tilt" data-tilt="3">
                <div className="term__bar"><i></i><i></i><i></i><span className="tag">bash</span></div>
                <pre>
<span className="pl"># install the core + your provider</span>{"\n"}
pip install -r namma_agent/requirements.txt{"\n\n"}
<span className="pl"># add your key</span>{"\n"}
cp namma_agent/.env.example .env{"\n"}
<span className="ac">ANTHROPIC_API_KEY</span>=sk-ant-...{"\n\n"}
<span className="pl"># run it</span>{"\n"}
python -m namma_agent --server{"\n"}
<span className="ok">→ chat ready at http://127.0.0.1:8000</span>
                </pre>
              </div>
            </div>
          </div>

          <div className="pixel-band pixel-corners" data-reveal="scale" style={{ textAlign: "center", marginTop: "var(--section-y-sm)" }}>
            <div className="pixel-field" aria-hidden="true"></div>
            <span className="eyebrow"><span className="pixel-mark" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i></span>&nbsp; Your agent, your advantage</span>
            <h2 style={{ margin: "var(--s-3) auto var(--s-4)", maxWidth: "22ch" }}>Intelligence for everyone, kept on your own machine.</h2>
            <p className="muted" style={{ marginInline: "auto", maxWidth: "46ch" }}>Name it whatever you like, point it at any model, and make it yours.</p>
            <div className="row" style={{ justifyContent: "center", marginTop: "var(--s-6)" }}><a href="#top" onClick={sc("top")} className="btn btn--primary btn--lg" data-magnetic>Run it now</a><a href="#/docs" className="btn btn--secondary btn--lg">Read the docs</a></div>
          </div>
        </section>
      </main>

      <Footer />
    </>
  );
}
