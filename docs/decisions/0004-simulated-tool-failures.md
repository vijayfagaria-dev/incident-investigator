# 4. Tools that fail on purpose, without crashing anything

*Decided 21 October 2026.*

**The problem.** Real investigations deal with tools that time out, go down, or return only
part of their data. The system has to cope, and we need to test that it does.

**What we chose.** Each incident can say how its tools misbehave: the first two calls time
out, logs from one data centre are lost, the list of changes is down. The failures are
added around the tools, so the tools themselves stay simple. One component runs every tool
call: it checks the request, tries a briefly failing call up to three times, stops calling
a tool that keeps failing, and always hands back a result. A failure becomes "missing
evidence" in the report, never a crash.

**The cost.** Only the failures we chose to model are tested: slow calls, outages, and
data that is partly missing.
