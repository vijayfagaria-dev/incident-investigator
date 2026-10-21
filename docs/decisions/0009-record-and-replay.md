# 9. Recording every investigation so it can be watched again

*Decided 21 October 2026.*

**The problem.** Reviewers should be able to see exactly what happened in an evaluated
investigation without an AI key, long after the free service has changed.

**What we chose.** Every AI reply is recorded with its timing. The viewer plays an
investigation back exactly as it happened. It can also run the investigation code again,
answering each request from the recording.

**The cost.** Running the code again doesn't always match the recording, because recorded
replies come back much faster than they did live. Agents working at the same time can
finish in a different order, and two small details of the tool results depend on that
order. And a step that ran out of time live, while the AI service was busy, doesn't run out
of time again. 29 of the 30 evaluated single-agent runs come out identical. Playback is
always exact.
