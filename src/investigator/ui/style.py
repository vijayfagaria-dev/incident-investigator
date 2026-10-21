"""The page's look: restrained glass on a dark backdrop, and small HTML pieces.

Glass is kept to structural surfaces (the incident card, agent lanes, section frames);
dense text sits on near-opaque panels so it stays readable. Status colour always comes
with a word, and every piece of model-written text is escaped before it reaches the page.
"""

from html import escape

AGENT_COLOURS = {
    "orchestrator": "#a78bfa",
    "observability": "#38bdf8",
    "dependency": "#34d399",
    "reasoning": "#fbbf24",
    "critic": "#f472b6",
    "reporting": "#94a3b8",
    "solo": "#60a5fa",
}

CSS = """
<style>
:root {
  --glass: rgba(255, 255, 255, 0.06);
  --glass-edge: rgba(255, 255, 255, 0.13);
  --dense: rgba(11, 16, 28, 0.9);
  --text-dim: #9aa6bd;
  --ok: #3fb97a; --warn: #e0a83a; --fail: #f2665e; --info: #6aa5ff;
}
.stApp {
  background:
    radial-gradient(1100px 620px at 10% -8%, rgba(64, 120, 255, 0.24), transparent 60%),
    radial-gradient(900px 520px at 95% 6%, rgba(0, 196, 170, 0.16), transparent 60%),
    radial-gradient(800px 600px at 60% 110%, rgba(167, 139, 250, 0.14), transparent 60%),
    linear-gradient(180deg, #0d1424, #070a12 70%);
  background-attachment: fixed;
}
[data-testid="stHeader"] { background: transparent; }
[data-testid="stSidebar"] > div:first-child {
  background: rgba(10, 14, 26, 0.72);
  backdrop-filter: blur(18px) saturate(140%);
  -webkit-backdrop-filter: blur(18px) saturate(140%);
  border-right: 1px solid var(--glass-edge);
}
[data-testid="stVerticalBlockBorderWrapper"] {
  background: var(--glass);
  border: 1px solid var(--glass-edge) !important;
  border-radius: 16px;
  backdrop-filter: blur(16px) saturate(140%);
  -webkit-backdrop-filter: blur(16px) saturate(140%);
  box-shadow: 0 10px 40px rgba(0, 0, 0, 0.35), inset 0 1px 0 rgba(255, 255, 255, 0.05);
}
[data-baseweb="tab-list"] { gap: 6px; }
[data-baseweb="tab"] {
  background: var(--glass); border: 1px solid var(--glass-edge); border-radius: 10px;
  padding: 6px 14px;
}
.glass-card { background: var(--glass); border: 1px solid var(--glass-edge); border-radius: 16px;
  padding: 18px 20px; backdrop-filter: blur(16px) saturate(140%);
  -webkit-backdrop-filter: blur(16px) saturate(140%); margin-bottom: 12px; }
.dense { background: var(--dense); border: 1px solid rgba(255,255,255,0.08); border-radius: 12px;
  padding: 12px 14px; margin-bottom: 8px; }
.eyebrow { color: var(--text-dim); font-size: 12px; letter-spacing: 0.08em;
  text-transform: uppercase; }
.incident-title { font-size: 24px; font-weight: 650; margin: 2px 0 8px; }
.dim { color: var(--text-dim); font-size: 13px; }
.chip { display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: 12px;
  font-weight: 600; margin: 0 6px 4px 0; background: rgba(255,255,255,0.08); color: #cbd5e1; }
.chip.ok { background: rgba(63,185,122,0.16); color: var(--ok); }
.chip.warn { background: rgba(224,168,58,0.16); color: var(--warn); }
.chip.fail { background: rgba(242,102,94,0.16); color: var(--fail); }
.chip.info { background: rgba(106,165,255,0.16); color: var(--info); }
.lanes { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; }
.lane { background: var(--glass); border: 1px solid var(--glass-edge); border-radius: 14px;
  padding: 10px 12px; backdrop-filter: blur(14px); -webkit-backdrop-filter: blur(14px); }
.lane .name { font-weight: 650; font-size: 13px; }
.lane .state { font-size: 12px; margin-top: 2px; }
.lane .counts { font-size: 11.5px; color: var(--text-dim); margin-top: 4px; }
.lane.working { box-shadow: 0 0 0 1px var(--lane-colour), 0 0 18px -4px var(--lane-colour);
  animation: pulse 1.6s ease-in-out infinite; }
@keyframes pulse {
  50% { box-shadow: 0 0 0 1px var(--lane-colour), 0 0 26px -2px var(--lane-colour); }
}
.step { display: grid; grid-template-columns: 120px 1fr; gap: 10px; align-items: start; }
.step .who { font-weight: 650; font-size: 12.5px; }
.step .what { font-size: 13.5px; }
.step ul { margin: 4px 0 0 0; padding-left: 18px; color: var(--text-dim); font-size: 12.5px; }
.step.failed .what { color: var(--fail); }
.meter { height: 8px; border-radius: 999px; background: rgba(255,255,255,0.08); overflow: hidden; }
.meter > span { display: block; height: 100%; border-radius: 999px; }
code { font-size: 12px; }
@media (prefers-reduced-transparency: reduce) {
  .glass-card, .lane, [data-testid="stVerticalBlockBorderWrapper"],
  [data-testid="stSidebar"] > div:first-child {
    background: #121a2c !important; backdrop-filter: none !important;
    -webkit-backdrop-filter: none !important;
  }
}
@media (prefers-reduced-motion: reduce) { .lane.working { animation: none; } }
</style>
"""

STATUS_KINDS = {"waiting": "", "working": "info", "done": "ok", "failed": "fail"}
VERDICT_KINDS = {"accept": "ok", "challenge": "warn", "reject": "fail"}


def chip(text: str, kind: str = "") -> str:
    return f'<span class="chip {kind}">{escape(text)}</span>'


def agent_label(agent: str) -> str:
    colour = AGENT_COLOURS.get(agent, "#cbd5e1")
    return f'<span class="who" style="color:{colour}">{escape(agent)}</span>'


def meter(fraction: float, colour: str) -> str:
    width = max(0.0, min(1.0, fraction)) * 100
    return f'<div class="meter"><span style="width:{width:.0f}%;background:{colour}"></span></div>'


def bullet_list(items: list[str] | tuple[str, ...]) -> str:
    if not items:
        return ""
    return "<ul>" + "".join(f"<li>{escape(item)}</li>" for item in items) + "</ul>"
