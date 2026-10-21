# incident-investigator

When an online service breaks, an engineer has to work out why, often under pressure and
with misleading clues. This project gets a team of six AI agents to do that investigation:
they look through the service's logs, measurements and recent changes, argue about possible
causes, and write a report that shows the evidence for each conclusion. When the evidence
isn't enough, the report says so instead of guessing.

The agents work on a pretend online brokerage, with problems we created on purpose and
clues that point the wrong way. Their results are compared with a single AI agent doing the
same job alone.
