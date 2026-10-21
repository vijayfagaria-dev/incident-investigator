# How to use it

## Watch recorded investigations (no key needed)

```sh
uv sync --extra ui
uv run investigator ui
```

This opens a page in your browser. Pick an incident and press **Replay** to watch the
agents work through it, step by step. Nothing is sent to the AI: every investigation shown
was recorded when it was evaluated.

## Run a new investigation

The agents use an AI model hosted by NVIDIA, which is free to use within a rate limit.

1. Sign in at [build.nvidia.com](https://build.nvidia.com) and create an API key. You
   don't need a payment card.
2. Copy `.env.example` to `.env` and put your key in it.
3. Run:

```sh
uv run investigator investigate T03                  # the team of agents
uv run investigator investigate T03 --system single  # the single agent, for comparison
```

A team investigation takes 10 to 20 minutes, a single agent about 5. Most of that is
waiting for the free service.

## All commands

| Command | What it does |
|---|---|
| `investigator ui` | Open the viewer |
| `investigator investigate <incident>` | Investigate an incident and print the report |
| `investigator eval run --out <folder>` | Run every test incident through both systems, three times each |
| `investigator eval report <folder>` | Score those runs and write a summary |
| `investigator data list` | List the incidents |
| `investigator data render <incident> --out <folder>` | Save an incident's data as files to look at |
| `investigator tools call <tool> --incident <incident> --args '<json>'` | Try one tool by hand |

## What it relies on

- NVIDIA's hosted AI model, free and rate-limited, only for new investigations.
- A few open-source Python packages, listed in `pyproject.toml`.
- Optionally, [Ollama](https://ollama.com) to run a small AI model on your own computer
  (`--profile ollama`). Small models do much worse at this task.
