# 2. A free AI model, behind one simple connection

*Decided 21 October 2026.*

**The problem.** The project had to cost nothing to run. Most free AI services either
needed a paid upgrade (Mistral) or allowed too few requests for one investigation (Groq,
Gemini, OpenRouter). Models small enough to run on our own laptop were too weak.

**What we chose.** NVIDIA's free hosted models. We tested the candidates on a short
investigation with a decoy, and picked Nemotron 3 Ultra: it got the right answer and was
the fastest of the large models. Every agent, and the single agent we compare against,
uses the same model, so teamwork is the only difference. All calls go through one
connection, so switching provider is a settings change.

If Nemotron still fails after its retries, the same request goes to GLM-5.3, the backup,
and the investigation carries on.

**The cost.** Results depend on a free service whose models, limits and speed can change.
A request answered by the backup breaks the "same model" rule, so every run records which
model answered each request, and the results count how many went to the backup.
