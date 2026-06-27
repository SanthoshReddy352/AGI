import { Link } from "react-router-dom";
import { GitHub, Telegram } from "./icons.jsx";
import { scrollToId } from "./Nav.jsx";

// Section links scroll when already on the landing page; otherwise they route
// home first. Kept simple: landing anchors use the hash + scroll helper.
function Sec({ id, label }) {
  return (
    <a href={`#${id}`} onClick={(e) => { e.preventDefault(); scrollToId(id); }}>{label}</a>
  );
}

export default function Footer() {
  return (
    <footer className="footer-x">
      <div className="shell">
        <div className="footer-x__top">
          <div className="footer-x__brand">
            <div className="word">Namma Agent</div>
            <p>A cloud-only personal AI assistant you run yourself. Intelligence for everyone.</p>
            <div className="social-ico socials">
              <a href="https://github.com/SanthoshReddy352/Namma-Agent" aria-label="GitHub"><GitHub /></a>
              <a href="#" aria-label="Telegram"><Telegram /></a>
            </div>
          </div>
          <div className="footer-col">
            <h4>Capabilities</h4>
            <Sec id="capabilities" label="Tools" />
            <Sec id="memory" label="Memory" />
            <Sec id="graph" label="Knowledge graph" />
            <Sec id="learn" label="Learning Room" />
          </div>
          <div className="footer-col">
            <h4>Run it</h4>
            <Sec id="providers" label="Providers" />
            <Sec id="start" label="Get started" />
            <a href="https://github.com/SanthoshReddy352/Namma-Agent">GitHub</a>
          </div>
          <div className="footer-col">
            <h4>Docs</h4>
            <Link to="/docs">Getting started</Link>
            <Link to="/docs#config">Configuration</Link>
            <Link to="/docs#architecture">Architecture</Link>
          </div>
        </div>
        <div className="footer-x__bottom">
          <span>© 2026 Santhosh Reddy and the Namma Agent contributors. MIT.</span>
          <div className="row-links"><Link to="/docs">Docs</Link><a href="#">License</a></div>
        </div>
      </div>
      <div className="footer-x__sig" aria-hidden="true">NAMMA AGENT</div>
    </footer>
  );
}
